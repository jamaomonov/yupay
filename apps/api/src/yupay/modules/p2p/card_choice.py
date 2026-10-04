"""Which card a new reservation goes on, and how far its amount may be bumped (spec §5.3)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, time
from typing import Final

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ConflictError
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.p2p.parsing import TASHKENT

MAX_BUMP: Final = 99
_LOCK_NAMESPACE: Final = b"p2p-card-daily-limit:"


def card_lock_key(card_id: str) -> int:
    """A stable signed 64-bit ``pg_advisory_xact_lock`` key for one card.

    Derived from the card id rather than Python's ``hash`` (salted per process),
    so every API process takes the same lock for the same card.
    """
    digest = hashlib.blake2b(_LOCK_NAMESPACE + card_id.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def _lock_limited(db: AsyncSession, cards: Sequence[P2PCard]) -> None:
    """Serialise reservations per card that has a daily limit, to the transaction's end.

    The daily room is a read-then-insert: without the lock two concurrent holds
    both read the same room and together pass the limit. The locks are taken in
    key order, all before any room is read, so two requests wanting overlapping
    cards can never wait on each other in a cycle. Cards without a limit stay
    lock-free; the open-amount index is all they need.
    """
    keys = sorted({card_lock_key(c.id) for c in cards if c.daily_limit_uzs is not None})
    for key in keys:
        await db.execute(select(func.pg_advisory_xact_lock(key)))


async def held_today(db: AsyncSession, card: P2PCard, now_: datetime) -> int:
    """Soʻm the card is committed to today: paid this Tashkent day plus open holds.

    Pending reservations count too, or concurrent holds could together pass the
    daily limit before any of them is paid.
    """
    start = datetime.combine(now_.astimezone(TASHKENT).date(), time(), TASHKENT)
    total = await db.scalar(
        select(func.coalesce(func.sum(P2PReservation.amount_uzs), 0)).where(
            P2PReservation.card_id == card.id,
            or_(
                and_(P2PReservation.status == "paid", P2PReservation.closed_at >= start),
                and_(P2PReservation.status == "pending", P2PReservation.expires_at > now_),
            ),
        )
    )
    return int(total or 0)


async def eligible_cards(
    db: AsyncSession, amount: int, now_: datetime
) -> list[tuple[P2PCard, int]]:
    """Cards that can take ``amount``, most daily room first, each with its bump cap.

    Every candidate card with a daily limit is locked (:func:`_lock_limited`)
    before its room is read, and the lock lasts until the caller's transaction
    ends — past the insert — so the room read here is still true at commit.

    Raises:
        ConflictError: ``p2p_no_card`` when no active card's bounds or daily room fit.
    """
    cards = (
        (
            await db.execute(
                select(P2PCard)
                .where(
                    P2PCard.active.is_(True),
                    P2PCard.min_amount_uzs <= amount,
                    P2PCard.max_amount_uzs >= amount,
                )
                .order_by(P2PCard.created_at, P2PCard.id)
            )
        )
        .scalars()
        .all()
    )
    await _lock_limited(db, cards)
    ranked: list[tuple[int, P2PCard, int]] = []
    for card in cards:
        room: int | None = None
        if card.daily_limit_uzs is not None:
            room = card.daily_limit_uzs - await held_today(db, card, now_)
            if room < amount:
                continue
        cap = min(MAX_BUMP, card.max_amount_uzs - amount)
        if room is not None:
            cap = min(cap, room - amount)
        ranked.append((room if room is not None else 10**18, card, cap))
    if not ranked:
        raise ConflictError("no card can take this amount", code="p2p_no_card")
    ranked.sort(key=lambda t: -t[0])  # stable: ties keep the oldest card first
    return [(card, cap) for _, card, cap in ranked]


__all__ = ["MAX_BUMP", "card_lock_key", "eligible_cards", "held_today"]
