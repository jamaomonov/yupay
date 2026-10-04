"""Exact-amount top-up reservations (spec §5.3).

The amount a reseller transfers is the only thing that ties a bank
notification back to them, so two open reservations on one card must never
share an amount. That rule lives in the partial unique index
``uq_p2p_reservations_open_amount`` (``holds_amount`` is true while pending and
through quarantine), not in a read-then-write here: two requests racing for
50 000 both try the insert, one wins, the other bumps to 50 001.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, UpstreamUnavailableError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fx.models import FxSnapshot
from yupay.modules.merchants import transactions
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.p2p.numbers import new_reservation_number
from yupay.modules.p2p.parsing import TASHKENT
from yupay.modules.p2p.settings import admits, load_settings
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate

log = get_logger("yupay.p2p.reservations")

RESERVATION_TTL: Final = timedelta(minutes=5)
QUARANTINE: Final = timedelta(minutes=10)
MAX_BUMP: Final = 99
_CENT: Final = Decimal("0.01")
_OPEN_AMOUNT_INDEX: Final = "uq_p2p_reservations_open_amount"


@dataclass(frozen=True)
class SweepResult:
    """Rows touched by one :func:`sweep` pass."""

    expired: int
    released: int


def expire_in_place(r: P2PReservation, now_: datetime) -> None:  # noqa: ARG001 - spec signature
    """Close a pending reservation past its five minutes; quarantine starts at expiry."""
    r.status = "expired"
    r.closed_at = r.expires_at
    r.quarantine_until = r.expires_at + QUARANTINE


async def _matched_today(db: AsyncSession, card: P2PCard, now_: datetime) -> int:
    start = datetime.combine(now_.astimezone(TASHKENT).date(), time(), TASHKENT)
    total = await db.scalar(
        select(func.coalesce(func.sum(P2PReservation.amount_uzs), 0)).where(
            P2PReservation.card_id == card.id,
            P2PReservation.status == "paid",
            P2PReservation.closed_at >= start,
        )
    )
    return int(total or 0)


async def _pick_card(db: AsyncSession, amount: int, now_: datetime) -> tuple[P2PCard, int]:
    """The card with the most daily room, and how far its amount may be bumped."""
    cards = (
        (
            await db.execute(
                select(P2PCard).where(
                    P2PCard.active.is_(True),
                    P2PCard.min_amount_uzs <= amount,
                    P2PCard.max_amount_uzs >= amount,
                )
            )
        )
        .scalars()
        .all()
    )
    best: tuple[int, P2PCard, int] | None = None
    for card in cards:
        room: int | None = None
        if card.daily_limit_uzs is not None:
            room = card.daily_limit_uzs - await _matched_today(db, card, now_)
            if room < amount:
                continue
        cap = min(MAX_BUMP, card.max_amount_uzs - amount)
        if room is not None:
            cap = min(cap, room - amount)
        score = room if room is not None else 10**18
        if best is None or score > best[0]:
            best = (score, card, cap)
    if best is None:
        raise ConflictError("no card can take this amount", code="p2p_no_card")
    return best[1], best[2]


async def _snapshot_id(db: AsyncSession, rate: Decimal) -> str | None:
    """The ``fx_snapshots`` row behind the guarded rate (orders.service precedent)."""
    found: str | None = await db.scalar(
        select(FxSnapshot.id)
        .where(FxSnapshot.base == "USD", FxSnapshot.quote == "UZS", FxSnapshot.rate == rate)
        .order_by(FxSnapshot.created_at.desc())
        .limit(1)
    )
    return found


def _violated_open_amount(exc: IntegrityError) -> bool:
    """Whether the failed insert broke the open-amount index (vs. one-pending / idem)."""
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None) or getattr(orig, "constraint_name", None)
    if name:
        return str(name) == _OPEN_AMOUNT_INDEX
    return _OPEN_AMOUNT_INDEX in str(exc)


async def _expire_stale(db: AsyncSession, r: P2PReservation, now_: datetime) -> None:
    """Expire ``r`` only if it is still pending in the database.

    A guarded UPDATE, not an ORM flush: a payment may have locked the row and
    marked it ``paid`` after we loaded it, and a flush by primary key would
    overwrite that. Callers that hold the row lock may use ``expire_in_place``.
    """
    await db.execute(
        update(P2PReservation)
        .where(
            P2PReservation.id == r.id,
            P2PReservation.status == "pending",
            P2PReservation.expires_at <= now_,
        )
        .values(
            status="expired",
            closed_at=P2PReservation.expires_at,
            quarantine_until=P2PReservation.expires_at + QUARANTINE,
        )
    )
    await db.refresh(r)


async def _after_race(
    db: AsyncSession, merchant_id: str, idempotency_key: str | None
) -> P2PReservation | None:
    """Resolve a one-pending / idempotency collision into the winner's row or a 409."""
    if idempotency_key is not None:
        same = await db.scalar(
            select(P2PReservation).where(
                P2PReservation.merchant_id == merchant_id,
                P2PReservation.idempotency_key == idempotency_key,
            )
        )
        if same is not None:
            return same
    pending = await db.scalar(
        select(P2PReservation).where(
            P2PReservation.merchant_id == merchant_id, P2PReservation.status == "pending"
        )
    )
    if pending is not None:
        raise ConflictError(
            "a top-up is already waiting", code="p2p_reservation_open", number=pending.number
        )
    return None


async def _guard_open(
    db: AsyncSession, merchant_id: str, idempotency_key: str | None, now_: datetime
) -> P2PReservation | None:
    """Refuse a second pending reservation; hand back an idempotent twin instead."""
    open_one = await db.scalar(
        select(P2PReservation).where(
            P2PReservation.merchant_id == merchant_id, P2PReservation.status == "pending"
        )
    )
    if open_one is not None and open_one.expires_at <= now_:
        await _expire_stale(db, open_one, now_)
    if open_one is None or open_one.status != "pending":
        return None
    if idempotency_key is not None and open_one.idempotency_key == idempotency_key:
        return open_one  # a concurrent twin committed after the caller's lookup
    raise ConflictError(
        "a top-up is already waiting", code="p2p_reservation_open", number=open_one.number
    )


async def reserve(
    db: AsyncSession, *, merchant_id: str, amount_uzs: int, idempotency_key: str | None
) -> P2PReservation:
    """Hold an exact amount for five minutes. See the module docstring.

    Raises:
        NotFoundError: ``p2p_disabled`` when the merchant is not admitted.
        ConflictError: ``p2p_reservation_open`` when one is already pending, or
            ``p2p_no_card`` when no active card's bounds or daily room fit.
        UpstreamUnavailableError: ``p2p_amount_busy`` when +99 is exhausted, or
            ``fx_unavailable`` when the rate gate rejects.
    """
    if idempotency_key is not None:
        prior = await db.scalar(
            select(P2PReservation).where(
                P2PReservation.merchant_id == merchant_id,
                P2PReservation.idempotency_key == idempotency_key,
            )
        )
        if prior is not None:
            return prior
    if not admits(await load_settings(db), merchant_id):
        raise NotFoundError("p2p top-up is not enabled", code="p2p_disabled")
    now_ = now()
    twin = await _guard_open(db, merchant_id, idempotency_key, now_)
    if twin is not None:
        return twin
    card, cap = await _pick_card(db, amount_uzs, now_)
    try:
        rate = await guarded_usd_rate(db, quote="UZS")
    except RateRejected as exc:
        raise UpstreamUnavailableError("rate unavailable", code="fx_unavailable") from exc
    snapshot_id = await _snapshot_id(db, rate)

    for bump in range(cap + 1):
        amount = amount_uzs + bump
        row = P2PReservation(
            id=new_id(),
            number=new_reservation_number(),
            card_id=card.id,
            amount_uzs=amount,
            purpose="merchant_deposit",
            merchant_id=merchant_id,
            fx_rate=rate,
            fx_snapshot_id=snapshot_id,
            amount_usd=(Decimal(amount) / rate).quantize(_CENT, rounding=ROUND_DOWN),
            status="pending",
            holds_amount=True,
            created_at=now_,
            expires_at=now_ + RESERVATION_TTL,
            idempotency_key=idempotency_key,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError as exc:
            if _violated_open_amount(exc):
                continue
            raced = await _after_race(db, merchant_id, idempotency_key)
            if raced is None:
                raise
            return raced
        log.info("p2p.reserved", number=row.number, amount_uzs=amount, card_last4=card.pan_last4)
        return row
    raise UpstreamUnavailableError("every nearby amount is held", code="p2p_amount_busy")


async def _own(db: AsyncSession, merchant_id: str, number: str, *, lock: bool) -> P2PReservation:
    stmt = select(P2PReservation).where(
        P2PReservation.number == number, P2PReservation.merchant_id == merchant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("top-up not found", code="p2p_not_found")
    return row


async def cancel(db: AsyncSession, *, merchant_id: str, number: str) -> P2PReservation:
    """Release a pending reservation; its amount stays quarantined (D3)."""
    r = await _own(db, merchant_id, number, lock=True)
    now_ = now()
    if r.status == "pending" and r.expires_at <= now_:
        expire_in_place(r, now_)
    if r.status == "cancelled":
        return r
    if r.status != "pending":
        raise ConflictError("this top-up can no longer be cancelled", code="p2p_not_cancellable")
    r.status, r.closed_at, r.quarantine_until = "cancelled", now_, now_ + QUARANTINE
    await db.flush()
    log.info("p2p.cancelled", number=r.number)
    return r


async def read(db: AsyncSession, *, merchant_id: str, number: str) -> P2PReservation:
    """One reservation; a stale ``pending`` is reported (and stored) as expired."""
    r = await _own(db, merchant_id, number, lock=False)
    now_ = now()
    if r.status == "pending" and r.expires_at <= now_:
        await _expire_stale(db, r, now_)
    return r


async def list_for_merchant(
    db: AsyncSession, *, merchant_id: str, limit: int, cursor: str | None
) -> tuple[list[P2PReservation], str | None]:
    """Newest first, keyset on ``(created_at, id)`` (merchants.transactions shape)."""
    limit = max(1, limit)
    stmt = select(P2PReservation).where(P2PReservation.merchant_id == merchant_id)
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (P2PReservation.created_at < at)
            | ((P2PReservation.created_at == at) & (P2PReservation.id < rid))
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(P2PReservation.created_at.desc(), P2PReservation.id.desc()).limit(
                    limit + 1
                )
            )
        )
        .scalars()
        .all()
    )
    page = rows[:limit]
    nxt = (
        transactions.encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    )
    return page, nxt


async def sweep(db: AsyncSession, *, now_: datetime) -> SweepResult:
    """Expire overdue pending rows, then release amounts whose quarantine ended."""
    expired = await db.execute(
        update(P2PReservation)
        .where(P2PReservation.status == "pending", P2PReservation.expires_at <= now_)
        .values(
            status="expired",
            closed_at=P2PReservation.expires_at,
            quarantine_until=P2PReservation.expires_at + QUARANTINE,
        )
    )
    released = await db.execute(
        update(P2PReservation)
        .where(
            P2PReservation.holds_amount.is_(True),
            P2PReservation.status.in_(("expired", "cancelled")),
            P2PReservation.quarantine_until <= now_,
        )
        .values(holds_amount=False)
    )
    return SweepResult(
        expired=getattr(expired, "rowcount", 0) or 0,
        released=getattr(released, "rowcount", 0) or 0,
    )


__all__ = [
    "MAX_BUMP",
    "QUARANTINE",
    "RESERVATION_TTL",
    "SweepResult",
    "cancel",
    "expire_in_place",
    "list_for_merchant",
    "read",
    "reserve",
    "sweep",
]
