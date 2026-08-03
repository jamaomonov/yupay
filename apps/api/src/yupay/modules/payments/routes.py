"""HTTP routes for ``payments``: customer intents, webhooks, admin views."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, UnauthorizedError, ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import Actor
from yupay.modules.payments import provider_admin, provider_analytics, provider_state
from yupay.modules.payments import service as svc
from yupay.modules.payments.provider_state import SLUG_TO_LOGICAL
from yupay.modules.payments.schemas import (
    AdminProviderDetailOut,
    AdminProviderListOut,
    AdminProviderSummary,
    PaymentAdminListOut,
    PaymentAdminOut,
    PaymentIntentIn,
    PaymentOut,
    PaymentWebhookListOut,
    PaymentWebhookOut,
    ProvidersOut,
    ProviderStatusOut,
    RefundIn,
    SetProviderStateIn,
    SimulateWebhookIn,
    WebhookResolveIn,
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


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


async def _resolve_actor(request: Request, db: AsyncSession) -> Actor:
    auth = request.headers.get("Authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user

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


async def _ensure_actor_owns_order(db: AsyncSession, *, actor: Actor, order_id: str) -> Order:
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


@router.get(
    "/providers", response_model=ProvidersOut, summary="Payment providers the storefront may show"
)
async def list_providers(db: Annotated[AsyncSession, Depends(db_session)]) -> ProvidersOut:
    slugs = list(SLUG_TO_LOGICAL.keys())
    states = await provider_state.get_states(db, slugs)
    out: list[ProviderStatusOut] = []
    for slug in slugs:
        status_ = provider_state.customer_status(slug, states[slug])
        if status_ is not None:
            out.append(ProviderStatusOut(slug=slug, status=status_))
    return ProvidersOut(providers=out)


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
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> PaymentOut:
    key = _require_idempotency_key(idempotency_key)
    actor = await _resolve_actor(request, db)
    await _ensure_actor_owns_order(db, actor=actor, order_id=body.order_id)
    payment = await svc.create_intent(
        db,
        order_id=body.order_id,
        provider=body.provider,
        return_url=body.return_url,
        idempotency_key=key,
    )
    return PaymentOut.model_validate(payment)


@router.get(
    "/by-order/{order_id}",
    response_model=PaymentOut,
    summary="Get the active payment intent for an order (owner-only)",
)
async def get_active_payment_route(
    order_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PaymentOut:
    """Used by the miniapp's order-detail page to surface a «pay now» button
    on a ``pending_payment`` order without re-creating the intent. Returns
    404 when no active intent exists (paid / refunded / cancelled order)."""
    actor = await _resolve_actor(request, db)
    await _ensure_actor_owns_order(db, actor=actor, order_id=order_id)
    payment = await svc.get_active_payment(db, order_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="no active payment for this order")
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
    limit: int = 50,
    offset: int = 0,
) -> PaymentAdminListOut:
    rows, total = await svc.list_payments_admin(
        db,
        order_id=order_id,
        provider=provider,
        status_filter=status_filter,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return PaymentAdminListOut(
        items=[PaymentAdminOut.model_validate(p) for p in rows],
        total=total,
    )


@admin_router.get(
    "/providers",
    response_model=AdminProviderListOut,
    summary="List logical payment providers with their current admin-controlled state",
)
async def admin_list_providers_route(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminProviderListOut:
    return AdminProviderListOut(providers=await provider_admin.list_admin_providers(db))


@admin_router.put(
    "/providers/{provider}/state",
    response_model=AdminProviderSummary,
    summary="Set a logical provider's state (writes every slug in its group)",
)
async def admin_set_provider_state_route(
    provider: str,
    body: SetProviderStateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminProviderSummary:
    key = normalize_idempotency_key(idempotency_key)
    scope = "payments.set_provider_state"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return AdminProviderSummary.model_validate(cached.body)
    out = await provider_admin.set_provider_state(
        db, provider=provider, state=body.state, changed_by=admin.id
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.get(
    "/providers/{provider}",
    response_model=AdminProviderDetailOut,
    summary="Per-provider analytics detail: volume, success rate, recent payments, incidents",
)
async def admin_provider_detail_route(
    provider: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    window: Annotated[Literal["today", "7d", "30d"], Query(description="Analytics window")] = "7d",
) -> AdminProviderDetailOut:
    lp = provider_state.LOGICAL_PROVIDERS.get(provider)
    if lp is None:
        raise NotFoundError("unknown payment provider", provider=provider)
    since = provider_analytics.window_start(window)
    summaries = await provider_admin.list_admin_providers(db)
    summary = next(s for s in summaries if s.provider == provider)
    return AdminProviderDetailOut(
        summary=summary,
        volume=await provider_analytics.volume_by_currency(db, slugs=lp.slugs, since=since),
        success_rate=await provider_analytics.success_rate(db, slugs=lp.slugs, since=since),
        recent=await provider_analytics.recent_payments(db, slugs=lp.slugs),
        incidents=await provider_analytics.incidents(db, slugs=lp.slugs),
    )


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
    payment = await svc.simulate_webhook(db, payment_id=payment_id, outcome=body.outcome)
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
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> PaymentAdminOut:
    key = _require_idempotency_key(idempotency_key)
    payment = await svc.refund_admin(
        db,
        payment_id=payment_id,
        admin_id=admin.id,
        amount=body.amount,
        reason=body.reason,
        idempotency_key=key,
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
    return PaymentWebhookListOut(items=[PaymentWebhookOut.model_validate(r) for r in rows])


@admin_webhook_router.post(
    "/{webhook_id}/mark-resolved",
    response_model=PaymentWebhookOut,
    summary="Admin: ack a rejected / stuck webhook record",
)
async def admin_resolve_webhook(
    webhook_id: str,
    body: WebhookResolveIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> PaymentWebhookOut:
    actor_email = admin.email or f"admin:{admin.id}"
    webhook = await svc.mark_webhook_resolved(
        db,
        webhook_id=webhook_id,
        actor_email=actor_email,
        reason=body.reason,
    )
    return PaymentWebhookOut.model_validate(webhook)
