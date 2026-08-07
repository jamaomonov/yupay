"""Capture, serve and expire chargeback evidence. See ADR-0044."""

from __future__ import annotations

from datetime import timedelta
from ipaddress import ip_address
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from yupay.core.client_ip import UNKNOWN_IP, client_ip
from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import NotFoundError
from yupay.core.logging import get_logger
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.evidence.schemas import (
    ClientHints,
    EvidencePackOut,
    OrderEventOut,
    OrderEvidenceOut,
)
from yupay.modules.orders.models import Order

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.evidence")

#: User-Agent strings are unbounded in principle and occasionally absurd in
#: practice. The column is 512; truncate rather than let a long header fail the
#: insert and take the order down with it.
_UA_MAX = 512
_LANG_MAX = 128


def _normalised_ip(request: Request) -> str | None:
    """The peer address, or ``None`` when it is absent or not a real address.

    ``client_ip`` may return the ``unknown`` sentinel, and the column is INET —
    writing a non-address there would fail the insert. A missing address is a
    weaker pack, never a failed order.
    """
    raw = client_ip(request)
    if raw == UNKNOWN_IP:
        return None
    try:
        return str(ip_address(raw))
    except ValueError:
        # Malformed X-Forwarded-For. Worth knowing about — under the current
        # edge config it should be impossible — but not worth an exception on
        # the checkout path.
        log.warning("evidence.ip_unparseable")
        return None


async def capture_for_order(
    db: AsyncSession,
    *,
    order_id: str,
    request: Request,
    hints: ClientHints | None = None,
    settings: Settings | None = None,
) -> None:
    """Record the request context behind ``order_id``. Idempotent, best-effort.

    Idempotent because order creation is: a retried ``Idempotency-Key`` returns
    the original order, and the original capture must win — the retry may come
    from a different address entirely (a phone that changed networks), and the
    context that matters is the one under which the order actually came to be.

    Never raises. Evidence is a safeguard for a dispute months away; refusing to
    sell something today because that safeguard failed to write is the wrong
    trade. Failures are logged and surface as a gap in the pack.
    """
    cfg = settings or get_settings()
    try:
        stmt = (
            pg_insert(OrderEvidence)
            .values(
                order_id=order_id,
                ip=_normalised_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:_UA_MAX] or None,
                accept_language=(request.headers.get("accept-language") or "")[:_LANG_MAX] or None,
                client_hints=hints.model_dump(exclude_none=True) if hints else {},
                purge_after=now() + timedelta(days=cfg.evidence_retention_days),
            )
            .on_conflict_do_nothing(index_elements=["order_id"])
        )
        # A SAVEPOINT, not a bare execute. The request's transaction is
        # committed after this route returns, so a statement that errors here
        # would poison it — swallowing the exception would not save the sale,
        # it would lose the order at commit time instead, which is the exact
        # failure this function claims to prevent. The nested block confines a
        # failed capture to itself.
        async with db.begin_nested():
            await db.execute(stmt)
    except Exception:
        log.exception("evidence.capture_failed", order_id=order_id)


async def get_pack(db: AsyncSession, *, order_id: str) -> EvidencePackOut:
    """Everything an acquirer asks for about one order, in one response."""
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found", extra={"order_id": order_id})

    capture = (
        await db.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one_or_none()

    return EvidencePackOut(
        order_id=order.id,
        status=order.status,
        total_charged=str(order.total_charged),
        currency=order.currency,
        created_at=order.created_at,
        paid_at=order.paid_at,
        delivered_at=order.delivered_at,
        capture=OrderEvidenceOut.model_validate(capture) if capture is not None else None,
        timeline=[OrderEventOut.model_validate(e) for e in order.events],
    )


async def purge_expired(db: AsyncSession) -> int:
    """Delete captures past their stamped ``purge_after``. Returns the count.

    Driven by the per-row stamp rather than by ``now() - retention``, so rows
    written under an earlier policy expire on the schedule they were promised.
    """
    result = await db.execute(delete(OrderEvidence).where(OrderEvidence.purge_after <= now()))
    # ``execute`` is typed as returning Result; a DELETE always yields a
    # CursorResult. Same suppression as orders.expire_stale_orders.
    return result.rowcount or 0  # type: ignore[attr-defined]


__all__ = ["capture_for_order", "get_pack", "purge_expired"]
