"""HTTP routes for the ``orders`` module.

User/guest surface mounted at ``/api/v1/orders``; admin surface mounted at
``/api/v1/admin/orders``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.dev_login import DEV_ADMIN_ID
from yupay.modules.auth.jwt import verify as verify_jwt
from yupay.modules.orders import service as svc
from yupay.modules.orders.models import Order
from yupay.modules.orders.schemas import (
    OrderAdminListOut,
    OrderAdminOut,
    OrderCreate,
    OrderListOut,
    OrderOut,
)
from yupay.modules.orders.service import Actor, build_item_display
from yupay.modules.users.models import User


def _attach_displays(order_out: OrderOut, order: Order, locale: str = "ru") -> None:
    """Mutate each item's ``display`` from the eagerly-loaded SKU chain."""
    for item_out, item in zip(order_out.items, order.items, strict=False):
        item_out.display = build_item_display(item, locale=locale)


def _to_order_out(order: Order, locale: str = "ru") -> OrderOut:
    out = OrderOut.model_validate(order)
    _attach_displays(out, order, locale=locale)
    return out


def _to_admin_order_out(order: Order, locale: str = "ru") -> OrderAdminOut:
    out = OrderAdminOut.model_validate(order)
    _attach_displays(out, order, locale=locale)
    return out


router = APIRouter(prefix="/orders", tags=["orders"])
admin_router = APIRouter(
    prefix="/admin/orders",
    tags=["admin:orders"],
    dependencies=[Depends(require_admin)],
)

# Idempotency keys shorter than this are rejected — they're too likely to collide.
_MIN_IDEMPOTENCY_KEY_LEN = 16


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
        # For lookup the guest must additionally pass the email as a query param so we
        # can identify which order; the token alone doesn't reveal it (only hash).
        email = request.query_params.get("email")
        if not email:
            raise ValidationError("email query param required for guest lookup")
        from yupay.core.config import get_settings
        from yupay.modules.auth.security import email_hash

        claims = verify_jwt(token, expected_kind="guest")
        expected = email_hash(email.strip().lower(), get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        actor = Actor(user_id=None, email=email.strip().lower())
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


# ---------- admin ----------


@admin_router.get("", response_model=OrderAdminListOut)
async def admin_list_orders(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    status_filter: Annotated[str | None, "status"] = None,
    limit: int = 50,
    offset: int = 0,
) -> OrderAdminListOut:
    """Admin order list with optional status filter."""
    orders, total = await svc.list_orders_admin(
        db,
        status_filter=status_filter,
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
