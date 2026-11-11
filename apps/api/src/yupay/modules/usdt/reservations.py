"""Exact-amount USDT top-up reservations (ADR-0104).

The amount a reseller sends is the only thing that ties a chain transfer back to
them, so two open reservations must never share an amount. That rule lives in
the partial unique index ``uq_usdt_reservations_open_amount`` (``holds_amount``
is true while pending and through quarantine), not in a read-then-write here:
two requests racing for 1000.00 both try the insert, one wins, the other bumps
to 1000.01. Same shape as ``p2p.reservations``, with one address instead of
cards and no exchange rate (1 USDT = 1 USD).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationError,
)
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants import transactions
from yupay.modules.p2p.integrity import violated_constraint
from yupay.modules.p2p.numbers import ALPHABET
from yupay.modules.usdt.models import UsdtReservation
from yupay.modules.usdt.settings import admits, load_settings

log = get_logger("yupay.usdt.reservations")

RESERVATION_TTL: Final = timedelta(minutes=60)
QUARANTINE: Final = timedelta(minutes=60)
CENT: Final = Decimal("0.01")
#: Bump up to +0.99: a reseller asked for 1000 is never told to send 1001.
MAX_BUMP_CENTS: Final = 99
_OPEN_AMOUNT_INDEX: Final = "uq_usdt_reservations_open_amount"
_RACE_INDEXES: Final = ("uq_usdt_reservations_one_pending", "uq_usdt_reservations_idem")


@dataclass(frozen=True)
class SweepResult:
    """Rows touched by one :func:`sweep` pass."""

    expired: int
    released: int


def new_number() -> str:
    """A fresh public number, ``U`` + 7 Crockford characters (random, not sequential)."""
    return "U" + "".join(secrets.choice(ALPHABET) for _ in range(7))


def _same_intent(prior: UsdtReservation, amount: Decimal) -> UsdtReservation:
    """Return ``prior`` if a replay asks for its amount or one it was bumped from.

    Raises:
        ConflictError: ``usdt_idempotency_mismatch`` when the key was used for
            another amount.
    """
    gap = prior.amount_usdt - amount
    if not Decimal(0) <= gap <= CENT * MAX_BUMP_CENTS:
        raise ConflictError(
            "this Idempotency-Key was used for another amount", code="usdt_idempotency_mismatch"
        )
    return prior


async def _expire_stale(db: AsyncSession, r: UsdtReservation, now_: datetime) -> None:
    """Expire ``r`` only if it is still pending in the database (a guarded UPDATE).

    A flush by primary key could overwrite a ``paid`` the intake wrote after we
    loaded the row.
    """
    await db.execute(
        update(UsdtReservation)
        .where(
            UsdtReservation.id == r.id,
            UsdtReservation.status == "pending",
            UsdtReservation.expires_at <= now_,
        )
        .values(
            status="expired",
            closed_at=UsdtReservation.expires_at,
            quarantine_until=UsdtReservation.expires_at + QUARANTINE,
        )
    )
    await db.refresh(r)


async def _prior(db: AsyncSession, merchant_id: str, key: str) -> UsdtReservation | None:
    found: UsdtReservation | None = await db.scalar(
        select(UsdtReservation).where(
            UsdtReservation.merchant_id == merchant_id, UsdtReservation.idempotency_key == key
        )
    )
    return found


async def _pending(db: AsyncSession, merchant_id: str) -> UsdtReservation | None:
    found: UsdtReservation | None = await db.scalar(
        select(UsdtReservation).where(
            UsdtReservation.merchant_id == merchant_id, UsdtReservation.status == "pending"
        )
    )
    return found


async def _guard_open(
    db: AsyncSession, merchant_id: str, key: str | None, amount: Decimal, now_: datetime
) -> UsdtReservation | None:
    """Refuse a second pending reservation; hand back an idempotent twin instead."""
    open_one = await _pending(db, merchant_id)
    if open_one is not None and open_one.expires_at <= now_:
        await _expire_stale(db, open_one, now_)
    if open_one is None or open_one.status != "pending":
        return None
    if key is not None and open_one.idempotency_key == key:
        return _same_intent(open_one, amount)
    raise ConflictError(
        "a top-up is already waiting", code="usdt_reservation_open", number=open_one.number
    )


async def _after_race(
    db: AsyncSession, merchant_id: str, key: str | None, amount: Decimal
) -> UsdtReservation | None:
    """Resolve a one-pending / idempotency collision into the winner's row or a 409."""
    if key is not None and (same := await _prior(db, merchant_id, key)) is not None:
        return _same_intent(same, amount)
    if (pending := await _pending(db, merchant_id)) is not None:
        raise ConflictError(
            "a top-up is already waiting", code="usdt_reservation_open", number=pending.number
        )
    return None


def _validate_amount(amount: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if amount != amount.quantize(CENT):
        raise ValidationError("amount has more than two decimals", code="usdt_amount_precision")
    if not lo <= amount <= hi:
        raise ValidationError(
            "amount out of bounds",
            code="usdt_amount_out_of_bounds",
            min_amount=format(lo, "f"),
            max_amount=format(hi, "f"),
        )
    return amount


async def reserve(
    db: AsyncSession, *, merchant_id: str, amount: Decimal, idempotency_key: str | None
) -> UsdtReservation:
    """Hold an exact USDT amount for 60 minutes, bumping by a cent when it is taken.

    Raises:
        NotFoundError: ``usdt_disabled`` when the merchant is not admitted.
        ValidationError: ``usdt_amount_precision`` / ``usdt_amount_out_of_bounds``.
        ConflictError: ``usdt_reservation_open`` when one is already pending, or
            ``usdt_idempotency_mismatch`` when the key was used for another amount.
        UpstreamUnavailableError: ``usdt_amount_busy`` when every amount up to
            +0.99 is held.
    """
    if idempotency_key is not None and (prior := await _prior(db, merchant_id, idempotency_key)):
        _same_intent(prior, amount)
        if prior.status == "pending" and prior.expires_at <= now():
            await _expire_stale(db, prior, now())
        return prior
    s = await load_settings(db)
    if not admits(s, merchant_id) or s.address is None:
        raise NotFoundError("usdt top-up is not enabled", code="usdt_disabled")
    amount = _validate_amount(amount, s.min_amount_usd, s.max_amount_usd)
    now_ = now()
    if (twin := await _guard_open(db, merchant_id, idempotency_key, amount, now_)) is not None:
        return twin
    for bump in range(MAX_BUMP_CENTS + 1):
        row = UsdtReservation(
            id=new_id(),
            number=new_number(),
            merchant_id=merchant_id,
            address=s.address,
            amount_usdt=amount + CENT * bump,
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
            hit = violated_constraint(exc, (_OPEN_AMOUNT_INDEX, *_RACE_INDEXES))
            if hit == _OPEN_AMOUNT_INDEX:
                continue
            if hit is None:
                raise
            if (raced := await _after_race(db, merchant_id, idempotency_key, amount)) is None:
                raise
            return raced
        log.info("usdt.reserved", number=row.number, amount_usdt=str(row.amount_usdt))
        return row
    raise UpstreamUnavailableError("every nearby amount is held", code="usdt_amount_busy")


async def _own(db: AsyncSession, merchant_id: str, number: str, *, lock: bool) -> UsdtReservation:
    stmt = select(UsdtReservation).where(
        UsdtReservation.number == number, UsdtReservation.merchant_id == merchant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("top-up not found", code="usdt_not_found")
    return row


async def cancel(db: AsyncSession, *, merchant_id: str, number: str) -> UsdtReservation:
    """Release a pending reservation; its amount stays quarantined.

    A transfer sent before the cancel still pays it: matching is by block time
    inside ``[created_at, closed_at]``, whatever the status.
    """
    r = await _own(db, merchant_id, number, lock=True)
    now_ = now()
    if r.status == "pending" and r.expires_at <= now_:
        r.status, r.closed_at = "expired", r.expires_at
        r.quarantine_until = r.expires_at + QUARANTINE
    if r.status == "cancelled":
        return r
    if r.status != "pending":
        raise ConflictError("this top-up can no longer be cancelled", code="usdt_not_cancellable")
    r.status, r.closed_at, r.quarantine_until = "cancelled", now_, now_ + QUARANTINE
    await db.flush()
    log.info("usdt.cancelled", number=r.number)
    return r


async def read(db: AsyncSession, *, merchant_id: str, number: str) -> UsdtReservation:
    """One reservation; a stale ``pending`` is reported (and stored) as expired."""
    r = await _own(db, merchant_id, number, lock=False)
    now_ = now()
    if r.status == "pending" and r.expires_at <= now_:
        await _expire_stale(db, r, now_)
    return r


async def list_for_merchant(
    db: AsyncSession, *, merchant_id: str, limit: int, cursor: str | None
) -> tuple[list[UsdtReservation], str | None]:
    """Newest first, keyset on ``(created_at, id)`` (merchants.transactions shape)."""
    limit = max(1, limit)
    stmt = select(UsdtReservation).where(UsdtReservation.merchant_id == merchant_id)
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (UsdtReservation.created_at < at)
            | ((UsdtReservation.created_at == at) & (UsdtReservation.id < rid))
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(UsdtReservation.created_at.desc(), UsdtReservation.id.desc()).limit(
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
        update(UsdtReservation)
        .where(UsdtReservation.status == "pending", UsdtReservation.expires_at <= now_)
        .values(
            status="expired",
            closed_at=UsdtReservation.expires_at,
            quarantine_until=UsdtReservation.expires_at + QUARANTINE,
        )
    )
    released = await db.execute(
        update(UsdtReservation)
        .where(
            UsdtReservation.holds_amount.is_(True),
            UsdtReservation.status.in_(("expired", "cancelled", "paid")),
            UsdtReservation.quarantine_until <= now_,
        )
        .values(holds_amount=False)
    )
    return SweepResult(
        expired=getattr(expired, "rowcount", 0) or 0,
        released=getattr(released, "rowcount", 0) or 0,
    )


__all__ = [
    "CENT",
    "MAX_BUMP_CENTS",
    "QUARANTINE",
    "RESERVATION_TTL",
    "SweepResult",
    "cancel",
    "list_for_merchant",
    "new_number",
    "read",
    "reserve",
    "sweep",
]
