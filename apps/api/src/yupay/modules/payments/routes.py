"""HTTP routes for ``payments``: customer intents, webhooks, admin views."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.admin.api import require_admin
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import Actor
from yupay.modules.payments import service as svc
from yupay.modules.payments.gateways import available_providers
from yupay.modules.payments.schemas import (
    PaymentAdminListOut,
    PaymentAdminOut,
    PaymentIntentIn,
    PaymentOut,
    PaymentWebhookListOut,
    PaymentWebhookOut,
    RefundIn,
    SimulateWebhookIn,
)
from yupay.modules.users.models import User

router = APIRouter(prefix="/payments", tags=["payments"])
admin_router = APIRouter(
    prefix="/admin/payments",
    tags=["admin:payments"],
    dependencies=[Depends(require_admin)],
)
admin_webhook_router = APIRouter(
    prefix="/admin/webhooks",
    tags=["admin:webhooks"],
    dependencies=[Depends(require_admin)],
)
webhook_router = APIRouter(prefix="/webhooks/payments", tags=["webhooks:payments"])


async def _resolve_actor(request: Request, db: AsyncSession) -> Actor:
    auth = request.headers.get("Authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user  # noqa: PLC0415

        user = await resolve_user(db, token)
        return Actor(user_id=user.id, email=None)
    if scheme == "Guest":
        claims = authjwt.verify(token, expected_kind="guest")
        # The route requires the email as a query param so we can rebuild the hash.
        email = request.query_params.get("email")
        if not email:
            raise ValidationError("email query param required for guest payments")
        expected = email_hash(email.strip().lower(), get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        return Actor(user_id=None, email=email.strip().lower())
    raise UnauthorizedError("authorization required")


async def _ensure_actor_owns_order(
    db: AsyncSession, *, actor: Actor, order_id: str
) -> Order:
    stmt = select(Order).where(Order.id == order_id)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if actor.user_id is not None:
        if order.user_id != actor.user_id:
            raise HTTPException(status_code=404, detail="order not found")
    elif (order.guest_email or "").lower() != (actor.email or "").lower():
        raise HTTPException(status_code=404, detail="order not found")
    return order


# ---------- customer ----------


@router.get("/providers", summary="List provider slugs currently usable")
async def list_providers() -> dict[str, list[str]]:
    return {"providers": available_providers()}


@router.post(
    "/intents",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create or reuse a payment intent for an order",
)
async def create_intent_route(
    body: PaymentIntentIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PaymentOut:
    actor = await _resolve_actor(request, db)
    await _ensure_actor_owns_order(db, actor=actor, order_id=body.order_id)
    payment = await svc.create_intent(
        db,
        order_id=body.order_id,
        provider=body.provider,
        return_url=body.return_url,
    )
    return PaymentOut.model_validate(payment)


@router.get(
    "/{payment_id}",
    response_model=PaymentOut,
    summary="Look up a single payment (owner-only)",
)
async def get_payment_route(
    payment_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PaymentOut:
    actor = await _resolve_actor(request, db)
    payment = await svc.get_payment(db, payment_id)
    await _ensure_actor_owns_order(db, actor=actor, order_id=payment.order_id)
    return PaymentOut.model_validate(payment)


# ---------- webhooks ----------


@webhook_router.post("/{provider}", summary="Provider webhook receiver")
async def receive_webhook(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, str]:
    body = await request.body()
    try:
        payment = await svc.handle_webhook(
            db, provider=provider, headers=request.headers, body=body
        )
    except ValidationError:
        # Per ADR-0012: reject with 400 so providers can retry. Do not 200 a bad signature.
        raise
    if payment is None:
        return {"status": "duplicate"}
    return {"status": "processed", "payment_id": payment.id}


# ---------- admin ----------


@admin_router.get("", response_model=PaymentAdminListOut)
async def admin_list_payments(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    order_id: str | None = None,
    provider: str | None = None,
    status_filter: Annotated[str | None, "status"] = None,
) -> PaymentAdminListOut:
    rows = await svc.list_payments_admin(
        db,
        order_id=order_id,
        provider=provider,
        status_filter=status_filter,
    )
    return PaymentAdminListOut(items=[PaymentAdminOut.model_validate(p) for p in rows])


@admin_router.get("/{payment_id}", response_model=PaymentAdminOut)
async def admin_get_payment(
    payment_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PaymentAdminOut:
    payment = await svc.get_payment(db, payment_id)
    return PaymentAdminOut.model_validate(payment)


@admin_router.post(
    "/{payment_id}/simulate-webhook",
    response_model=PaymentAdminOut,
    summary="Dev-only: synthesise a webhook to flip the mock payment",
)
async def admin_simulate_webhook(
    payment_id: str,
    body: SimulateWebhookIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PaymentAdminOut:
    if get_settings().is_prod:
        raise HTTPException(status_code=403, detail="simulate-webhook is dev-only")
    payment = await svc.simulate_webhook(
        db, payment_id=payment_id, outcome=body.outcome
    )
    return PaymentAdminOut.model_validate(payment)


@admin_router.post(
    "/{payment_id}/refund",
    response_model=PaymentAdminOut,
    summary="Admin-initiated refund (full or partial)",
)
async def admin_refund_payment(
    payment_id: str,
    body: RefundIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> PaymentAdminOut:
    payment = await svc.refund_admin(
        db,
        payment_id=payment_id,
        admin_id=admin.id,
        amount=body.amount,
        reason=body.reason,
    )
    return PaymentAdminOut.model_validate(payment)


# ---------- webhook log ----------


@admin_webhook_router.get(
    "",
    response_model=PaymentWebhookListOut,
    summary="Recent incoming payment webhooks, with verify status and raw payload",
)
async def admin_list_webhooks(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    provider: str | None = None,
    signature_ok: bool | None = None,
    limit: int = 100,
) -> PaymentWebhookListOut:
    rows = await svc.list_webhooks_admin(
        db,
        provider=provider,
        signature_ok=signature_ok,
        limit=max(1, min(limit, 500)),
    )
    return PaymentWebhookListOut(
        items=[PaymentWebhookOut.model_validate(r) for r in rows]
    )
