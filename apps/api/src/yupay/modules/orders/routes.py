"""HTTP routes for the ``orders`` module.

User/guest surface mounted at ``/api/v1/orders``; admin surface mounted at
``/api/v1/admin/orders``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import (
    AccountSuspendedError,
    PaymentUnavailableAbroadError,
    UnauthorizedError,
    ValidationError,
)
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.dev_login import DEV_ADMIN_ID
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.auth.jwt import verify as verify_jwt
from yupay.modules.evidence.service import capture_for_order, ip_country_from
from yupay.modules.fulfillment.schemas import DeliveryListOut, DeliveryOut
from yupay.modules.orders import service as svc
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.orders.revenue import order_charged_usd
from yupay.modules.orders.risk import _is_trusted_buyer, _veto_decision
from yupay.modules.orders.schemas import (
    ClaimOut,
    OrderAdminListOut,
    OrderAdminOut,
    OrderCreate,
    OrderFailIn,
    OrderListOut,
    OrderOut,
)
from yupay.modules.orders.service import Actor, build_item_display, succeeded_provider_for
from yupay.modules.users.models import User
from yupay.modules.users.service import is_email_banned

log = get_logger("yupay.orders.routes")


def _attach_displays(order_out: OrderOut, order: Order, locale: str = "ru") -> None:
    """Mutate each item's ``display`` from the eagerly-loaded SKU chain."""
    for item_out, item in zip(order_out.items, order.items, strict=False):
        item_out.display = build_item_display(item, locale=locale)


def _to_order_out(order: Order, locale: str = "ru") -> OrderOut:
    out = OrderOut.model_validate(order)
    out.payment_provider = succeeded_provider_for(order)
    _attach_displays(out, order, locale=locale)
    return out


def _to_admin_order_out(order: Order, locale: str = "ru") -> OrderAdminOut:
    out = OrderAdminOut.model_validate(order)
    out.payment_provider = succeeded_provider_for(order)
    # Free of extra queries: `_order_load_options` has already walked
    # items → sku, which is all this needs.
    out.charged_usd = order_charged_usd(order)
    _attach_displays(out, order, locale=locale)
    return out


async def _to_admin_orders_out(
    db: AsyncSession, orders: Sequence[Order], locale: str = "ru"
) -> list[OrderAdminOut]:
    """The admin DTO for a page of orders, with everything a query is needed for.

    Sits between the routes and :func:`_to_admin_order_out` because the fields
    it fills cannot be read off the eagerly-loaded row: the reseller's title
    lives in another module's table, and the fulfilment state is derived from
    the tasks and the deposit ledger. Both are batched **once per page** rather
    than once per order — the listing serves up to 500 rows — and the detail
    route reaches it with a one-element list so there is one composition and
    not two.

    ``merchants.order_status`` is imported here rather than at module scope for
    the reason the delivery route imports ``fulfillment.service`` inside its
    handler: it pulls in ``fulfillment.service``, which reaches back into this
    module's own service, and this file is imported while the ``/api/v1`` route
    stack is still being built.

    Args:
        db: Session. The caller owns the transaction.
        orders: The page, already loaded through ``_order_load_options``.
        locale: Which translation of the item display to attach.

    Returns:
        One DTO per order, in the order given.
    """
    from yupay.modules.merchants import order_status as merchant_order_status

    titles = await svc.merchant_titles_for(db, orders)
    # The reseller's own answer to "why has this stopped", not a second one:
    # the admin and `/merchant/v1` must not be able to disagree about an order
    # the operator is about to explain to the merchant reading it. The two
    # deposit numbers ride along because that read already had to take them.
    states = await merchant_order_status.order_stop_states(db, orders=orders)
    out: list[OrderAdminOut] = []
    for order in orders:
        dto = _to_admin_order_out(order, locale=locale)
        if order.merchant_id is not None:
            dto.merchant_title = titles.get(order.merchant_id)
        state = states[order.id]
        dto.failure_reason = state.reason
        dto.deposit_charged_usd = state.deposit_charged
        dto.deposit_returned_usd = state.deposit_returned
        out.append(dto)
    return out


router = APIRouter(prefix="/orders", tags=["orders"])
admin_router = APIRouter(
    prefix="/admin/orders",
    tags=["admin:orders"],
    dependencies=[Depends(require_admin)],
)

_MIN_IDEMPOTENCY_KEY_LEN = MIN_IDEMPOTENCY_KEY_LENGTH

#: Which surface placed the order — ``web`` / ``miniapp`` / ``bot``. Advisory
#: and client-declared: it answers "where did this come from" for an operator
#: and gates nothing, so an absent or unrecognised value records as ``unknown``
#: rather than being trusted verbatim.
SURFACE_HEADER = "X-Yupay-Surface"


async def _resolve_actor(
    request: Request,
    body: OrderCreate,
    db: AsyncSession,
) -> Actor:
    """Pull Authorization out of the request and decide who the actor is.

    Accepts ``Bearer <access>`` (user) or ``Guest <guest_access>`` (guest).
    """
    auth = request.headers.get("Authorization")
    if not auth:
        raise UnauthorizedError("authorization required")
    scheme, _, token = auth.partition(" ")

    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user

        user = await resolve_user(db, token)
        return Actor(user_id=user.id, email=None)

    if scheme == "Guest":
        claims = verify_jwt(token, expected_kind="guest")
        if not body.guest_email:
            raise ValidationError("guest_email is required for guest checkout")
        # The token's ``sub`` is ``guest:<email_hash>``; we cross-check email below by
        # re-hashing in the auth/security helper. Doing it inline keeps the route thin.
        from yupay.core.config import get_settings
        from yupay.modules.auth.security import email_hash

        normalised = body.guest_email.strip().lower()
        expected = email_hash(normalised, get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        # Guest checkout creates no user row, so without this a suspended
        # customer walks straight past the ban by not logging in. It closes the
        # door on the banned identity, not on the person — another address still
        # works, and ADR-0045 says so rather than implying otherwise.
        if await is_email_banned(db, normalised):
            raise AccountSuspendedError("this account has been suspended")
        return Actor(user_id=None, email=normalised)

    raise UnauthorizedError("invalid authorization scheme")


async def _enforce_precharge_veto(
    request: Request,
    body: OrderCreate,
    db: AsyncSession,
    actor: Actor,
) -> None:
    """Enforcement point B of the pre-charge geo veto (ADR-0063).

    Runs after ``_resolve_actor`` and before ``svc.create_order`` — refusing
    here rolls the whole transaction back, so no order row and no evidence
    row are ever written for a vetoed guest. Fed from the LIVE request
    rather than a stored ``order_evidence`` row, unlike enforcement point A
    (the acquirers' own pre-charge stages, see ``risk.precharge_veto``):
    there is nothing to read yet at this point in the request.

    Wrapped in the same fail-open contract as the rest of ``orders.risk`` —
    a broken check must never stop checkout — except for the veto's own
    refusal, which is a decision, not a failure, and must propagate. The DB
    read (``_is_trusted_buyer``) runs inside its own ``db.begin_nested()``
    SAVEPOINT, the same pattern ``orders.risk._gather``/``precharge_veto_full``
    use: without it, a DB-level failure here (a statement timeout, a dropped
    connection — not just a Python exception) leaves the *whole* request
    transaction aborted, and ``svc.create_order``'s very next statement dies
    with ``InFailedSqlTransactionError`` -> 500, even though this function
    itself correctly failed open. The savepoint isolates that failure to the
    trusted-buyer check alone.
    """
    from yupay.core.config import get_settings

    cfg = get_settings()
    country = ip_country_from(request.headers.get("cf-ipcountry"))
    timezone = body.client_hints.timezone if body.client_hints else None
    try:
        async with db.begin_nested():
            is_trusted = await _is_trusted_buyer(db, actor.user_id)
    except Exception:
        log.exception("orders.risk.veto_failed")
        return
    reason = _veto_decision(is_trusted, country, timezone, cfg)
    if reason is not None:
        raise PaymentUnavailableAbroadError(
            "payment from abroad requires a signed-in account with order history"
        )


@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an order (idempotent)",
)
async def create_order_route(
    body: OrderCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
    surface: Annotated[str | None, Header(alias=SURFACE_HEADER)] = None,
) -> OrderOut:
    """Create a new order on behalf of the authenticated user or guest."""
    # Its own bucket, because the global limiter is a coarse flood-stopper
    # sized for public reads (600/minute) — loose enough that order creation
    # needs its own number. Sixty a minute is far above what a person does and
    # far below what a script would want; a carrier NAT is the reason it is not
    # tighter still.
    await guard_ip(request, bucket="order-create")
    if not idempotency_key or len(idempotency_key) < _MIN_IDEMPOTENCY_KEY_LEN:
        raise ValidationError(
            f"Idempotency-Key header is required (>={_MIN_IDEMPOTENCY_KEY_LEN} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    actor = await _resolve_actor(request, body, db)
    await _enforce_precharge_veto(request, body, db, actor)
    order = await svc.create_order(
        db,
        body,
        actor=actor,
        idempotency_key=idempotency_key,
        source=svc.normalise_source(surface),
    )
    # After the order exists, so the capture can never be the reason a sale
    # fails; idempotent, so a retried Idempotency-Key keeps the original
    # context rather than overwriting it with the retry's. See ADR-0044.
    await capture_for_order(
        db,
        order_id=order.id,
        request=request,
        hints=body.client_hints,
    )
    return _to_order_out(order)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order_route(
    order_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> OrderOut:
    """Look up an order. Owner-only (404 otherwise)."""
    # Tolerate both user Bearer and guest tokens. We don't need the request body here, so
    # build a placeholder OrderCreate for ``_resolve_actor`` to read the email out of
    # the JWT itself.
    auth = request.headers.get("Authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user

        user = await resolve_user(db, token)
        actor = Actor(user_id=user.id, email=None)
    elif scheme == "Guest":
        # For lookup the guest must additionally pass their email so we can
        # identify which order — the token alone doesn't reveal it (only a
        # hash). Read from a header, not a query param: a query param lands
        # in Caddy / proxy access logs and browser history, a header doesn't.
        email = request.headers.get("X-Guest-Email")
        if not email:
            raise ValidationError("X-Guest-Email header required for guest lookup")
        from yupay.core.config import get_settings
        from yupay.modules.auth.security import email_hash

        normalised = email.strip().lower()
        claims = verify_jwt(token, expected_kind="guest")
        expected = email_hash(normalised, get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        actor = Actor(user_id=None, email=normalised)
    else:
        raise UnauthorizedError("authorization required")

    order = await svc.get_order_for_actor(db, order_id, actor=actor)
    return _to_order_out(order)


@router.get("", response_model=OrderListOut)
async def list_orders_route(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> OrderListOut:
    """List orders for the logged-in user. Guests get this view via the email link."""
    orders = await svc.list_orders_for_actor(db, actor=Actor(user_id=user.id, email=None))
    return OrderListOut(items=[_to_order_out(o) for o in orders])


@router.post("/claim", response_model=ClaimOut, summary="Claim guest orders for the logged-in user")
async def claim_orders_route(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> ClaimOut:
    """Migrate any guest orders matching the caller's (verified) email to their account."""
    count = await svc.claim_orders_for_user(db, user=user)
    return ClaimOut(claimed=count)


# ---------- admin ----------


@admin_router.get("", response_model=OrderAdminListOut)
async def admin_list_orders(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    status_filter: Annotated[str | None, "status"] = None,
    merchant_id: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> OrderAdminListOut:
    """Admin order list with optional status filter and created-at date range.

    ``since``/``until`` are inclusive bounds on ``Order.created_at``, ISO 8601
    query params (matching the audit feed's convention — see
    ``modules/audit/routes.py``). ``q`` matches an order id (full or prefix),
    an owner's user id, a guest email, the owner's name/email, a catalog
    brand or product name, or a merchant title; it filters in the database so
    a result on page 7 is still findable from page 1, and ``total`` describes
    the search rather than the page.

    ``merchant_id`` narrows to one reseller exactly. ``q`` can match a
    merchant title and that is the wrong tool for this job: titles collide
    and titles get renamed, and "everything this account bought" is a
    question about an id.
    """
    orders, total = await svc.list_orders_admin(
        db,
        status_filter=status_filter,
        merchant_id=merchant_id,
        q=q,
        since=since,
        until=until,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return OrderAdminListOut(
        items=await _to_admin_orders_out(db, orders),
        total=total,
    )


@admin_router.get("/{order_id}", response_model=OrderAdminOut)
async def admin_get_order(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> OrderAdminOut:
    order = await svc.get_order_admin(db, order_id)
    return (await _to_admin_orders_out(db, [order]))[0]


@admin_router.post("/{order_id}/cancel", response_model=OrderAdminOut)
async def admin_cancel_order(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> OrderAdminOut:
    """Admin-initiated cancellation. Only valid from ``pending_payment``."""
    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    order = await svc.cancel_order_admin(db, order_id, admin_id=actor_id)
    return (await _to_admin_orders_out(db, [order]))[0]


@admin_router.get("/{order_id}/deliveries", response_model=DeliveryListOut)
async def admin_list_order_deliveries(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> DeliveryListOut:
    """Delivered artifacts (codes / receipts) for an order — support's answer to
    "the code doesn't work".

    Returns the artifact unfiltered, unlike the customer route: an operator
    reconciling with a supplier needs the internal fields. Because a voucher
    code is a bearer instrument, the read is written to the order timeline with
    the acting admin (``admin.deliveries_viewed``).
    """
    # Lazy import: orders.service <-> fulfillment.service is a known cycle.
    from yupay.modules.fulfillment import service as fulfillment_svc

    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    rows = await fulfillment_svc.list_deliveries_for_order_admin(
        db, order_id=order_id, admin_id=actor_id
    )
    return DeliveryListOut(items=[DeliveryOut.model_validate(r) for r in rows])


@admin_router.post("/{order_id}/resend-delivery-email", status_code=status.HTTP_204_NO_CONTENT)
async def admin_resend_delivery_email(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> None:
    """Re-send the delivered email (codes + magic link) to the order's address.

    For the support case "I never got the email". The mail can only go to the
    address stored on the order — never to an address the caller supplies — so
    this cannot be used to redirect someone's codes. Recorded on the order
    timeline; a no-op (still 204) when the order has no guest email or nothing
    has been delivered yet.
    """
    from yupay.modules.notifications.service import resend_guest_delivery_email

    order = await svc.get_order_admin(db, order_id)
    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    if not order.guest_email:
        # Registered buyers get their codes in-app; there is no address to mail.
        return
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="admin.delivery_email_resent",
            payload={},
            actor=f"admin:{actor_id}",
        )
    )
    await db.flush()
    await resend_guest_delivery_email(order_id, order.guest_email)


@admin_router.post("/{order_id}/fail", response_model=OrderAdminOut)
async def admin_mark_order_failed(
    order_id: str,
    body: OrderFailIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> OrderAdminOut:
    """Close a paid-but-undeliverable order as ``failed`` (reason required).

    The only manual status change exposed to admins, and deliberately a narrow
    one: legal from ``paid``/``fulfilling``/``fulfilled`` only. Before payment
    use ``/cancel``; after delivery the customer already holds the goods, so
    the correct action is a refund. Cancels open fulfilment tasks and pending
    payments — see ``orders.service.mark_order_failed_admin``. Moves no money.
    """
    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    order = await svc.mark_order_failed_admin(db, order_id, admin_id=actor_id, reason=body.reason)
    return (await _to_admin_orders_out(db, [order]))[0]
