"""Exact-amount USDT top-up reservations (ADR-0104).

The amount a reseller sends is the only thing that ties a chain transfer back to
them, so two open reservations must never share an amount. That rule lives in
the partial unique index ``uq_usdt_reservations_open_amount`` (``holds_amount``
is true while pending and through quarantine), not in a read-then-write here:
two requests racing for the same 1000.00 both try the insert, one wins, the
other is offered 1000.xx. Same shape as ``p2p.reservations``, with one address instead of
cards and no exchange rate (1 USDT = 1 USD).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationError,
)
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants import transactions
from yupay.modules.p2p.integrity import violated_constraint
from yupay.modules.p2p.numbers import ALPHABET
from yupay.modules.usdt.models import UsdtNetwork, UsdtReservation
from yupay.modules.usdt.settings import admits, is_open, load_settings

log = get_logger("yupay.usdt.reservations")

#: How long the reseller has to send (owner, 2026-11-11: 30 min, as FZR does).
RESERVATION_TTL: Final = timedelta(minutes=30)
QUARANTINE: Final = timedelta(minutes=60)
CENT: Final = Decimal("0.01")
#: When the asked amount is held, the reseller is offered it plus random
#: cents (+0.01…+0.99) instead, and decides: take that or change the amount.
#: The owner's choice (2026-11-11): a free amount is reserved exactly as asked.
MAX_BUMP_CENTS: Final = 99
#: Reservations one merchant may open per hour. Each closed one holds its
#: amount for an hour, so without a cap one reseller could reserve-and-cancel
#: every cent of a popular amount and lock everyone else out.
HOURLY_LIMIT: Final = 10
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


def _same_intent(prior: UsdtReservation, amount: Decimal, network: str) -> UsdtReservation:
    """Return ``prior`` if a replay asks for exactly its amount on its network.

    Raises:
        ConflictError: ``usdt_idempotency_mismatch`` when the key was used for
            another amount.
    """
    if prior.amount_usdt != amount or prior.network != network:
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
    db: AsyncSession,
    merchant_id: str,
    key: str | None,
    amount: Decimal,
    network: str,
    now_: datetime,
) -> UsdtReservation | None:
    """Refuse a second pending reservation; hand back an idempotent twin instead."""
    open_one = await _pending(db, merchant_id)
    if open_one is not None and open_one.expires_at <= now_:
        await _expire_stale(db, open_one, now_)
    if open_one is None or open_one.status != "pending":
        return None
    if key is not None and open_one.idempotency_key == key:
        return _same_intent(open_one, amount, network)
    raise ConflictError(
        "a top-up is already waiting", code="usdt_reservation_open", number=open_one.number
    )


async def _after_race(
    db: AsyncSession, merchant_id: str, key: str | None, amount: Decimal, network: str
) -> UsdtReservation | None:
    """Resolve a one-pending / idempotency collision into the winner's row or a 409."""
    if key is not None and (same := await _prior(db, merchant_id, key)) is not None:
        return _same_intent(same, amount, network)
    if (pending := await _pending(db, merchant_id)) is not None:
        raise ConflictError(
            "a top-up is already waiting", code="usdt_reservation_open", number=pending.number
        )
    return None


async def suggest(
    db: AsyncSession, address: str, amount: Decimal, ceiling: Decimal
) -> Decimal | None:
    """A free amount near ``amount``: it plus random cents, or ``None`` if all are held.

    Only a suggestion — nothing is held until the reseller accepts it and asks
    for that exact amount, which may by then be taken too (they get another).
    """
    candidates = [c for k in range(1, MAX_BUMP_CENTS + 1) if (c := amount + CENT * k) <= ceiling]
    held = set(
        (
            await db.execute(
                select(UsdtReservation.amount_usdt).where(
                    UsdtReservation.address == address,
                    UsdtReservation.holds_amount.is_(True),
                    UsdtReservation.amount_usdt.in_(candidates),
                )
            )
        ).scalars()
    )
    free = [c for c in candidates if c not in held]
    return secrets.choice(free) if free else None


async def _guard_rate(db: AsyncSession, merchant_id: str, now_: datetime) -> None:
    recent = await db.scalar(
        select(func.count())
        .select_from(UsdtReservation)
        .where(
            UsdtReservation.merchant_id == merchant_id,
            UsdtReservation.created_at > now_ - timedelta(hours=1),
        )
    )
    if (recent or 0) >= HOURLY_LIMIT:
        raise RateLimitedError("too many top-ups this hour", code="usdt_too_many")


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
    db: AsyncSession,
    *,
    merchant_id: str,
    network: str,
    amount: Decimal,
    idempotency_key: str | None,
) -> UsdtReservation:
    """Hold exactly ``amount`` USDT on ``network`` for 30 minutes.

    When another reservation holds it, nothing is reserved: the 409 carries a
    free ``suggested`` amount (the request plus random cents) for the reseller
    to accept or replace.

    Raises:
        NotFoundError: ``usdt_disabled`` when the merchant is not admitted, or
            ``usdt_network_disabled`` when that chain is off or has no address.
        ValidationError: ``usdt_amount_precision`` / ``usdt_amount_out_of_bounds``.
        ConflictError: ``usdt_reservation_open`` when one is already pending, or
            ``usdt_idempotency_mismatch`` when the key was used for another amount.
        RateLimitedError: ``usdt_too_many`` past ``HOURLY_LIMIT`` an hour.
        ConflictError: ``usdt_amount_taken`` (with ``suggested``) when the amount
            is held; ``usdt_amount_busy`` when every nearby amount is held too.
    """
    if idempotency_key is not None and (prior := await _prior(db, merchant_id, idempotency_key)):
        _same_intent(prior, amount, network)
        if prior.status == "pending" and prior.expires_at <= now():
            await _expire_stale(db, prior, now())
        return prior
    s = await load_settings(db)
    if not admits(s, merchant_id):
        raise NotFoundError("usdt top-up is not enabled", code="usdt_disabled")
    net = await db.get(UsdtNetwork, network)
    if net is None or not is_open(net) or net.address is None:
        raise NotFoundError("this network is not enabled", code="usdt_network_disabled")
    amount = _validate_amount(amount, s.min_amount_usd, s.max_amount_usd)
    now_ = now()
    if (
        twin := await _guard_open(db, merchant_id, idempotency_key, amount, network, now_)
    ) is not None:
        return twin
    await _guard_rate(db, merchant_id, now_)
    row = UsdtReservation(
        id=new_id(),
        number=new_number(),
        merchant_id=merchant_id,
        network=network,
        address=net.address,
        amount_usdt=amount,
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
        if hit is None:
            raise
        if hit == _OPEN_AMOUNT_INDEX:
            if (offer := await suggest(db, net.address, amount, s.max_amount_usd)) is None:
                raise ConflictError(
                    "this amount and every nearby one is held", code="usdt_amount_busy"
                ) from exc
            raise ConflictError(
                "this amount is held by another top-up",
                code="usdt_amount_taken",
                suggested=format(offer, "f"),
            ) from exc
        if (raced := await _after_race(db, merchant_id, idempotency_key, amount, network)) is None:
            raise
        return raced
    log.info("usdt.reserved", number=row.number, amount_usdt=str(row.amount_usdt))
    return row


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
