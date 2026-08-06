"""HTTP routes for the ``orders`` module.

User/guest surface mounted at ``/api/v1/orders``; admin surface mounted at
``/api/v1/admin/orders``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.core.ids import new_id
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.dev_login import DEV_ADMIN_ID
from yupay.modules.auth.jwt import verify as verify_jwt
from yupay.modules.fulfillment.schemas import DeliveryListOut, DeliveryOut
from yupay.modules.orders import service as svc
from yupay.modules.orders.models import Order, OrderEvent
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
    _attach_displays(out, order, locale=locale)
    return out


router = APIRouter(prefix="/orders", tags=["orders"])
admin_router = APIRouter(
    prefix="/admin/orders",
    tags=["admin:orders"],
    dependencies=[Depends(require_admin)],
)

_MIN_IDEMPOTENCY_KEY_LEN = MIN_IDEMPOTENCY_KEY_LENGTH


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
        return Actor(user_id=None, email=normalised)

    raise UnauthorizedError("invalid authorization scheme")


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
) -> OrderOut:
    """Create a new order on behalf of the authenticated user or guest."""
    if not idempotency_key or len(idempotency_key) < _MIN_IDEMPOTENCY_KEY_LEN:
        raise ValidationError(
            f"Idempotency-Key header is required (>={_MIN_IDEMPOTENCY_KEY_LEN} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    actor = await _resolve_actor(request, body, db)
    order = await svc.create_order(
        db,
        body,
        actor=actor,
        idempotency_key=idempotency_key,
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
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> OrderAdminListOut:
    """Admin order list with optional status filter and created-at date range.

    ``since``/``until`` are inclusive bounds on ``Order.created_at``, ISO 8601
    query params (matching the audit feed's convention — see
    ``modules/audit/routes.py``).
    """
    orders, total = await svc.list_orders_admin(
        db,
        status_filter=status_filter,
        since=since,
        until=until,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return OrderAdminListOut(
        items=[_to_admin_order_out(o) for o in orders],
        total=total,
    )


@admin_router.get("/{order_id}", response_model=OrderAdminOut)
async def admin_get_order(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> OrderAdminOut:
    order = await svc.get_order_admin(db, order_id)
    return _to_admin_order_out(order)


@admin_router.post("/{order_id}/cancel", response_model=OrderAdminOut)
async def admin_cancel_order(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> OrderAdminOut:
    """Admin-initiated cancellation. Only valid from ``pending_payment``."""
    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    order = await svc.cancel_order_admin(db, order_id, admin_id=actor_id)
    return _to_admin_order_out(order)


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
    return _to_admin_order_out(order)
