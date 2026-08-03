"""Read-only per-provider analytics for the admin detail screen.

Aggregates the ``payments`` table (and ``payment_webhooks`` for incidents) over
a window, scoped to a logical provider's slug set (see
``provider_state.LOGICAL_PROVIDERS``). No PII in the ``recent`` list.

Status-bucket mapping
----------------------
``Payment.status`` (see ``PaymentStatus`` in ``schemas.py``) has seven values:
``pending``, ``requires_action``, ``succeeded``, ``failed``, ``cancelled``,
``refunded``, ``partially_refunded``. This module buckets them for the
success-rate metric as:

* **succeeded** = ``succeeded``, ``refunded``, ``partially_refunded`` — the
  payment attempt itself collected money at the gateway. A later refund
  reverses the money but does not retroactively make the *payment* a failure;
  refunds are their own audit trail (``payments.refund_admin`` /
  ``reverse_provider_payment``) and a separate concern from "did the customer
  successfully pay". ``volume_by_currency`` uses the same bucket, so refunded
  volume still counts as processed volume for the window (it is not netted
  against the refund).
* **failed** = ``failed``, ``cancelled`` — terminal, no money collected.
* **pending** = ``pending``, ``requires_action`` — not yet terminal.

These three buckets partition the full status vocabulary with no overlap, so
``succeeded + failed + pending`` always equals the window's total row count.

Incidents
---------
Mirrors ``admin.service.triage_payments`` exactly so the numbers agree with
the existing triage screen:

* ``stuck_pending``: ``Payment.status == "pending"`` older than
  ``stuck_after_minutes`` (default 30, matching
  ``admin.service._DEFAULT_STUCK_AFTER_MINUTES``).
* ``failed_webhooks``: ``PaymentWebhook.signature_ok is False`` OR
  ``PaymentWebhook.processed_at IS NULL``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.payments.models import Payment, PaymentWebhook
from yupay.modules.payments.schemas import (
    ProviderIncidentsOut,
    RecentPaymentOut,
    SuccessRateOut,
    VolumeRow,
)

Window = Literal["today", "7d", "30d"]

_WINDOWS: dict[Window, timedelta] = {
    "today": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# Partition of PaymentStatus (schemas.py) — see module docstring for rationale.
_SUCCEEDED_STATUSES: frozenset[str] = frozenset({"succeeded", "refunded", "partially_refunded"})
_FAILED_STATUSES: frozenset[str] = frozenset({"failed", "cancelled"})
_PENDING_STATUSES: frozenset[str] = frozenset({"pending", "requires_action"})

_RECENT_LIMIT = 20
# Matches admin.service._DEFAULT_STUCK_AFTER_MINUTES exactly (see incidents()).
_DEFAULT_STUCK_AFTER_MINUTES = 30


def window_start(window: Window) -> datetime:
    """UTC cutoff for ``window`` (``"today"``, ``"7d"``, or ``"30d"``).

    ``window`` is a closed ``Literal`` — FastAPI's ``Query`` validation on the
    route rejects anything else with a 422 before this is ever called, so
    there is no "unrecognised value" fallback to reason about here.
    """
    return now() - _WINDOWS[window]


async def volume_by_currency(
    db: AsyncSession, *, slugs: list[str], since: datetime
) -> list[VolumeRow]:
    """Succeeded-bucket payment volume grouped by currency within the window.

    A currency with only pending/failed attempts in the window has no row.
    """
    rows = (
        await db.execute(
            select(Payment.currency, func.sum(Payment.amount), func.count())
            .where(
                Payment.provider.in_(slugs),
                Payment.created_at >= since,
                Payment.status.in_(_SUCCEEDED_STATUSES),
            )
            .group_by(Payment.currency)
        )
    ).all()
    return [
        VolumeRow(
            currency=currency, amount=amount if amount is not None else Decimal(0), count=count
        )
        for currency, amount, count in rows
    ]


async def success_rate(db: AsyncSession, *, slugs: list[str], since: datetime) -> SuccessRateOut:
    """Succeeded / failed / pending counts + success percentage for the window."""
    rows = (
        await db.execute(
            select(Payment.status, func.count())
            .where(Payment.provider.in_(slugs), Payment.created_at >= since)
            .group_by(Payment.status)
        )
    ).all()
    succeeded = sum(count for status_, count in rows if status_ in _SUCCEEDED_STATUSES)
    failed = sum(count for status_, count in rows if status_ in _FAILED_STATUSES)
    pending = sum(count for status_, count in rows if status_ in _PENDING_STATUSES)
    total = succeeded + failed + pending
    success_pct = round(100 * succeeded / total, 1) if total else 0.0
    return SuccessRateOut(
        succeeded=succeeded, failed=failed, pending=pending, success_pct=success_pct
    )


async def recent_payments(
    db: AsyncSession, *, slugs: list[str], limit: int = _RECENT_LIMIT
) -> list[RecentPaymentOut]:
    """Last ``limit`` payments for the provider group, newest first.

    No PII: only id/order_id/status/amount/currency/created_at — never
    email/phone/user identifiers (see AGENTS.md §9).
    """
    rows = (
        await db.execute(
            select(Payment)
            .where(Payment.provider.in_(slugs))
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        RecentPaymentOut(
            id=p.id,
            order_id=p.order_id,
            status=p.status,  # type: ignore[arg-type]
            amount=p.amount,
            currency=p.currency,
            created_at=p.created_at,
        )
        for p in rows
    ]


async def incidents(
    db: AsyncSession,
    *,
    slugs: list[str],
    stuck_after_minutes: int = _DEFAULT_STUCK_AFTER_MINUTES,
) -> ProviderIncidentsOut:
    """Stuck-pending + failed-webhook counts, mirroring ``admin.triage_payments``."""
    cutoff = now() - timedelta(minutes=stuck_after_minutes)
    stuck = (
        await db.execute(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.provider.in_(slugs),
                Payment.status == "pending",
                Payment.created_at < cutoff,
            )
        )
    ).scalar_one()
    failed_webhooks = (
        await db.execute(
            select(func.count())
            .select_from(PaymentWebhook)
            .where(
                PaymentWebhook.provider.in_(slugs),
                (PaymentWebhook.signature_ok.is_(False)) | (PaymentWebhook.processed_at.is_(None)),
            )
        )
    ).scalar_one()
    return ProviderIncidentsOut(stuck_pending=int(stuck), failed_webhooks=int(failed_webhooks))


__all__ = [
    "Window",
    "incidents",
    "recent_payments",
    "success_rate",
    "volume_by_currency",
    "window_start",
]
