"""Audit timeline assembly.

Reads each event-bearing table separately (each with its own filters), merges
the rows in Python, sorts by timestamp DESC, and trims to the page size.

Sounds wasteful, but each per-source query is cheap (indexed by created_at)
and the union avoids a hot-loop of JSONB-aware UNION-ALL across five
different schemas. When a single source ever crosses ~10M rows we'll add
pg_partman + a materialised audit table; for now this is fine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import REDACTED_KEYS
from yupay.modules.fulfillment.models import FulfillmentAttempt
from yupay.modules.orders.models import OrderEvent
from yupay.modules.payments.models import PaymentAttempt, PaymentWebhook
from yupay.modules.wallet.models import WalletTransaction

# Type alias for one source feed.
AuditSourceName = str

_REDACTED_VALUE = "<redacted>"


def _redact(value: Any) -> Any:
    """Recursively mask blocklisted keys before a payload leaves this module.

    The five JSONB/dict columns fed into the timeline (``OrderEvent.payload``,
    ``PaymentAttempt.payload``, ``PaymentWebhook.payload``,
    ``FulfillmentAttempt.payload``, ``WalletTransaction.extra_metadata``) are
    mostly hand-curated by our own services, but ``PaymentWebhook.payload`` for
    a signature-valid webhook is the provider's raw parsed JSON body verbatim
    (see ``payments.service.handle_webhook``) — e.g. Octo's callback can carry
    a masked PAN + ``rrn`` (see ``payments.gateways.octo`` docstring). We don't
    control that shape, so mask by key rather than trusting the writer.

    Reuses ``core.logging.REDACTED_KEYS`` so the audit feed and the structured
    logger agree on what counts as sensitive. Recurses into nested dicts/lists
    since provider webhook bodies aren't guaranteed to be flat.
    """
    if isinstance(value, dict):
        return {
            k: _REDACTED_VALUE if str(k).lower() in REDACTED_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


@dataclass(frozen=True)
class AuditEvent:
    """Internal in-memory shape; pydantic-serialised at the route layer."""

    id: str
    ts: datetime
    source: AuditSourceName
    kind: str
    actor: str | None
    target_id: str | None
    target_kind: str | None
    payload: dict[str, Any] = field(default_factory=dict)


# ---------- per-source fetchers --------------------------------------------


async def _fetch_order_events(
    db: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    target_id: str | None,
    actor: str | None,
    limit: int,
) -> list[AuditEvent]:
    # `created_at` is the transaction start, so a settlement's three events
    # share it exactly; without the id the feed shuffles them on every read.
    stmt = (
        select(OrderEvent).order_by(OrderEvent.created_at.desc(), OrderEvent.id.desc()).limit(limit)
    )
    if since is not None:
        stmt = stmt.where(OrderEvent.created_at >= since)
    if until is not None:
        stmt = stmt.where(OrderEvent.created_at <= until)
    if target_id is not None:
        stmt = stmt.where(OrderEvent.order_id == target_id)
    if actor is not None:
        stmt = stmt.where(OrderEvent.actor == actor)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEvent(
            id=r.id,
            ts=r.created_at,
            source="order_event",
            kind=r.kind,
            actor=r.actor,
            target_id=r.order_id,
            target_kind="order",
            payload=dict(r.payload or {}),
        )
        for r in rows
    ]


async def _fetch_payment_attempts(
    db: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    target_id: str | None,
    actor: str | None,
    limit: int,
) -> list[AuditEvent]:
    stmt = select(PaymentAttempt).order_by(PaymentAttempt.created_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(PaymentAttempt.created_at >= since)
    if until is not None:
        stmt = stmt.where(PaymentAttempt.created_at <= until)
    if target_id is not None:
        stmt = stmt.where(PaymentAttempt.payment_id == target_id)
    rows = list((await db.execute(stmt)).scalars().all())
    out: list[AuditEvent] = []
    for r in rows:
        payload = dict(r.payload or {})
        # payment_attempts carry the admin id in payload for refunds; surface it.
        actor_v = f"admin:{payload['admin_id']}" if payload.get("admin_id") else None
        if actor is not None and actor_v != actor:
            continue
        out.append(
            AuditEvent(
                id=r.id,
                ts=r.created_at,
                source="payment_attempt",
                kind=f"payment.{r.kind}.{r.status}",
                actor=actor_v,
                target_id=r.payment_id,
                target_kind="payment",
                payload={**payload, "error": r.error},
            )
        )
    return out


async def _fetch_payment_webhooks(
    db: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    target_id: str | None,
    actor: str | None,
    limit: int,
) -> list[AuditEvent]:
    # actor isn't meaningful for inbound webhooks (no human pressed a button).
    if actor is not None:
        return []
    stmt = select(PaymentWebhook).order_by(PaymentWebhook.received_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(PaymentWebhook.received_at >= since)
    if until is not None:
        stmt = stmt.where(PaymentWebhook.received_at <= until)
    if target_id is not None:
        # Match on the external event id; the in-house webhook UUID isn't
        # something an operator types in.
        stmt = stmt.where(PaymentWebhook.external_event_id == target_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEvent(
            id=r.id,
            ts=r.received_at,
            source="payment_webhook",
            kind=(f"webhook.{r.provider}.{'ok' if r.signature_ok else 'rejected'}"),
            actor=None,
            target_id=r.external_event_id,
            target_kind="webhook",
            payload=dict(r.payload or {}),
        )
        for r in rows
    ]


async def _fetch_fulfillment_attempts(
    db: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    target_id: str | None,
    actor: str | None,
    limit: int,
) -> list[AuditEvent]:
    # fulfilment is always invoked by the saga, not by a human, so the
    # actor filter just rejects everything.
    if actor is not None:
        return []
    stmt = select(FulfillmentAttempt).order_by(FulfillmentAttempt.created_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(FulfillmentAttempt.created_at >= since)
    if until is not None:
        stmt = stmt.where(FulfillmentAttempt.created_at <= until)
    if target_id is not None:
        stmt = stmt.where(FulfillmentAttempt.task_id == target_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEvent(
            id=r.id,
            ts=r.created_at,
            source="fulfillment_attempt",
            kind=f"fulfillment.{r.kind}.{r.status}",
            actor=None,
            target_id=r.task_id,
            target_kind="fulfillment_task",
            payload={**(r.payload or {}), "error": r.error},
        )
        for r in rows
    ]


async def _fetch_wallet_transactions(
    db: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    target_id: str | None,
    actor: str | None,
    limit: int,
) -> list[AuditEvent]:
    stmt = select(WalletTransaction).order_by(WalletTransaction.created_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(WalletTransaction.created_at >= since)
    if until is not None:
        stmt = stmt.where(WalletTransaction.created_at <= until)
    if target_id is not None:
        # Either the reference (order/payment/manual id) or the txn id itself.
        stmt = stmt.where(
            or_(
                WalletTransaction.reference_id == target_id,
                WalletTransaction.id == target_id,
            )
        )
    if actor is not None:
        stmt = stmt.where(WalletTransaction.actor == actor)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEvent(
            id=r.id,
            ts=r.created_at,
            source="wallet_transaction",
            kind=f"wallet.{r.kind}",
            actor=r.actor,
            target_id=r.reference_id,
            target_kind=r.reference_type,
            payload={
                **(r.extra_metadata or {}),
                "wallet_transaction_id": r.id,
                "idempotency_key": r.idempotency_key,
            },
        )
        for r in rows
    ]


# ---------- public surface --------------------------------------------------


_ALL_SOURCES: tuple[AuditSourceName, ...] = (
    "order_event",
    "payment_attempt",
    "payment_webhook",
    "fulfillment_attempt",
    "wallet_transaction",
)

# Sources whose rows can carry an admin actor. Webhooks and fulfilment attempts
# never do (one is inbound from a provider, the other is the saga doing its job),
# so admin_only filters them out entirely.
_ADMIN_CAPABLE_SOURCES: tuple[AuditSourceName, ...] = (
    "order_event",
    "payment_attempt",
    "wallet_transaction",
)

_FETCHERS = {
    "order_event": _fetch_order_events,
    "payment_attempt": _fetch_payment_attempts,
    "payment_webhook": _fetch_payment_webhooks,
    "fulfillment_attempt": _fetch_fulfillment_attempts,
    "wallet_transaction": _fetch_wallet_transactions,
}


async def list_audit_events(
    db: AsyncSession,
    *,
    sources: Iterable[AuditSourceName] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = None,
    target_id: str | None = None,
    admin_only: bool = False,
    limit: int = 100,
) -> list[AuditEvent]:
    """Assemble the timeline. Fetches up to ``limit`` newest rows from each
    requested source, merges, sorts DESC by timestamp, trims to ``limit``.

    ``admin_only=True`` keeps only events whose actor starts with ``admin:`` —
    i.e. things humans did, with the admin role. Used by the Admin Activity
    view (UC7, ADR-0017). Sources without an actor (payment webhooks, saga
    fulfilment attempts) are skipped up front to avoid wasting per-source
    LIMIT slots on rows we'll discard.
    """
    chosen = tuple(sources) if sources is not None else _ALL_SOURCES
    chosen = tuple(s for s in chosen if s in _FETCHERS)
    if admin_only:
        chosen = tuple(s for s in chosen if s in _ADMIN_CAPABLE_SOURCES)
    if not chosen:
        return []
    capped_per_source = max(1, min(limit, 500))
    collected: list[AuditEvent] = []
    for s in chosen:
        rows = await _FETCHERS[s](
            db,
            since=since,
            until=until,
            target_id=target_id,
            actor=actor,
            limit=capped_per_source,
        )
        collected.extend(rows)
    if admin_only:
        collected = [e for e in collected if e.actor is not None and e.actor.startswith("admin:")]
    collected.sort(key=lambda e: e.ts, reverse=True)
    page = collected[:limit]
    # Redact only the page we're about to hand back — the per-source fetchers
    # may have pulled up to `limit` rows each, most of which get discarded by
    # the merge/trim above.
    return [replace(e, payload=_redact(e.payload)) for e in page]


__all__ = ["AuditEvent", "AuditSourceName", "list_audit_events"]
