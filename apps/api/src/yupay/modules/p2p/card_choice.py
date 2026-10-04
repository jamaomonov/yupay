"""Which card a new reservation goes on, and how far its amount may be bumped (spec §5.3)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Final

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ConflictError
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.p2p.parsing import TASHKENT

MAX_BUMP: Final = 99


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


__all__ = ["MAX_BUMP", "eligible_cards", "held_today"]
