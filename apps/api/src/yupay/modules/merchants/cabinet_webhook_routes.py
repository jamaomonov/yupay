"""The cabinet's webhook screen: configure the endpoint and read the log.

A second router over the same prefix as :mod:`cabinet_routes`, split off for
the reason ``admin_routes`` and ``catalog_b2b_routes`` were: one file had
passed AGENTS.md §6's soft limit, and the seam that costs nothing is the one
between "the account, its catalog and its orders" and "where we push to".

**These four writes used to be admin-only** (ADR-0070 §M3a): a reseller
changing their endpoint meant a support conversation. What made that the right
call then was SSRF — a stranger aiming our outbound worker at an address of
their choosing — and what makes handing it over right now is that the two
defences are in the facade rather than in the admin router.
``admin.validate_webhook_url`` refuses anything that is not https or that
names a private or loopback host at **save** time, and ``core.outbound`` pins
one resolved address per attempt at **send** time. Neither depends on who
called, which is the property that lets the caller change.
"""

from __future__ import annotations

from fastapi import APIRouter

from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.logging import get_logger
from yupay.modules.merchants import admin as merchant_admin
from yupay.modules.merchants import cabinet_webhooks
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.cabinet_schemas import (
    CabinetDeliveriesOut,
    CabinetWebhookOut,
    CabinetWebhookSecretOut,
    CabinetWebhookSetIn,
)
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed

log = get_logger("yupay.merchants.cabinet_webhook_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])


def _webhook_secret_out(configured: merchant_admin.ConfiguredWebhook) -> CabinetWebhookSecretOut:
    """Render a just-written hook, carrying the secret only if one was minted."""
    return CabinetWebhookSecretOut(
        **CabinetWebhookOut.model_validate(configured.webhook).model_dump(),
        secret=configured.secret,
    )


@router.get("/webhook", response_model=CabinetWebhookOut, summary="The configured endpoint")
async def read_webhook(user: CurrentUser, db: Db) -> CabinetWebhookOut:
    """404 until one has been set. Never carries the secret — no such field."""
    merchant = await merchant_of(db, user)
    return CabinetWebhookOut.model_validate(
        await merchant_admin.get_webhook(db, merchant_id=merchant.id)
    )


@router.put(
    "/webhook",
    response_model=CabinetWebhookSecretOut,
    summary="Point the webhook at a URL",
)
async def set_webhook(
    body: CabinetWebhookSetIn,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CabinetWebhookSecretOut:
    """Set the endpoint; the first call mints the signing secret and shows it once.

    Self-serve from M4 — until now this was an admin-only control and a
    reseller changing their endpoint meant a support conversation. The SSRF
    rules that made it admin-only are enforced by the facade
    (``admin.validate_webhook_url``: https, no private or loopback host) and
    the delivery client pins one resolved address per attempt, so the control
    is safe to hand over rather than merely convenient to.

    Setting a URL also clears ``disabled_at`` and the failure streak, which
    makes this the recovery path after an auto-disable.

    A retry carrying the same ``Idempotency-Key`` replays the original
    response with ``secret: null``: ``idempotent_responses`` has no reaper, so
    a usable signing key must never be persisted there. If the first response
    was lost, rotate.
    """
    merchant = await merchant_of(db, user)
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.cabinet_webhook_set:{merchant.id}"
    cached = await replayed(db, scope=scope, key=key, model=CabinetWebhookSecretOut)
    if cached is not None:
        return cached
    configured = await merchant_admin.set_webhook(db, merchant_id=merchant.id, url=body.url)
    out = _webhook_secret_out(configured)
    log.info("merchant.cabinet.webhook_set", merchant_id=merchant.id)
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
    )
    return out


@router.post(
    "/webhook/rotate-secret",
    response_model=CabinetWebhookSecretOut,
    summary="Replace the webhook signing secret",
)
async def rotate_webhook_secret(
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CabinetWebhookSecretOut:
    """Mint a new secret and show it once; the old one stops signing immediately.

    One live key at a time, unlike an API credential's overlapping rotation:
    there the merchant redeploys between issue and revoke and only they know
    when that finished, whereas here **we** are the sender and the switch is
    ours to make. A replay answers ``secret: null`` rather than rotating twice.
    """
    merchant = await merchant_of(db, user)
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.cabinet_webhook_rotate:{merchant.id}"
    cached = await replayed(db, scope=scope, key=key, model=CabinetWebhookSecretOut)
    if cached is not None:
        return cached
    configured = await merchant_admin.rotate_webhook_secret(db, merchant_id=merchant.id)
    out = _webhook_secret_out(configured)
    log.info("merchant.cabinet.webhook_secret_rotated", merchant_id=merchant.id)
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
    )
    return out


@router.delete(
    "/webhook",
    response_model=CabinetWebhookOut,
    summary="Stop delivering (keeps the row and the log)",
)
async def disable_webhook(
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CabinetWebhookOut:
    """A timestamp, never a DELETE: the log stays readable and turning it back
    on is a ``PUT`` with the URL, not a re-onboarding with a new secret."""
    merchant = await merchant_of(db, user)
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.cabinet_webhook_disable:{merchant.id}"
    cached = await replayed(db, scope=scope, key=key, model=CabinetWebhookOut)
    if cached is not None:
        return cached
    out = CabinetWebhookOut.model_validate(
        await merchant_admin.disable_webhook(db, merchant_id=merchant.id)
    )
    log.info("merchant.cabinet.webhook_disabled", merchant_id=merchant.id)
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


@router.get(
    "/webhook/deliveries",
    response_model=CabinetDeliveriesOut,
    summary="What we sent, where, and what came back",
)
async def list_deliveries(
    user: CurrentUser, db: Db, cursor: str | None = None, limit: int = 25
) -> CabinetDeliveriesOut:
    merchant = await merchant_of(db, user)
    return await cabinet_webhooks.list_deliveries(
        db, merchant_id=merchant.id, limit=max(1, min(limit, 100)), cursor=cursor
    )


__all__ = ["router"]
