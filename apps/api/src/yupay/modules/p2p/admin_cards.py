"""Admin routes for P2P cards: list with receive health, add, edit."""

from __future__ import annotations

from datetime import datetime, time

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.p2p.admin_deps import Admin, Db, parse_uuid
from yupay.modules.p2p.cards import normalize_pan, seal_pan
from yupay.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from yupay.modules.p2p.parsing import TASHKENT
from yupay.modules.p2p.schemas import P2PCardAdminOut, P2PCardCreateIn, P2PCardPatchIn

router = APIRouter()

log = get_logger("yupay.p2p.admin")


async def _card_stats(
    db: AsyncSession, cards: list[P2PCard]
) -> tuple[dict[str, int], dict[str, datetime], dict[str, bool]]:
    """Today's matched total per card id, plus last notification and chain verdict per last4.

    Receive health (``last_incoming_at``, ``chain_ok_last``) is keyed by the last
    four digits, because that is all a HUMO notification names. Two cards that
    share a last4 ("twins", e.g. a reissued card next to its predecessor) show
    the same health; only ``matched_today_uzs`` is per card.
    """
    start = datetime.combine(now().astimezone(TASHKENT).date(), time(), TASHKENT)
    matched = {
        cid: int(total)
        for cid, total in (
            await db.execute(
                select(P2PReservation.card_id, func.sum(P2PReservation.amount_uzs))
                .where(P2PReservation.status == "paid", P2PReservation.closed_at >= start)
                .group_by(P2PReservation.card_id)
            )
        ).all()
    }
    last4s = list({c.pan_last4 for c in cards})
    last_at = {
        k: at
        for k, at in (
            await db.execute(
                select(P2PIncoming.card_last4, func.max(P2PIncoming.received_at))
                .where(P2PIncoming.card_last4.in_(last4s))
                .group_by(P2PIncoming.card_last4)
            )
        ).all()
    }
    chain = {
        k: ok
        for k, ok in (
            await db.execute(
                select(P2PIncoming.card_last4, P2PIncoming.chain_ok)
                .where(P2PIncoming.card_last4.in_(last4s), P2PIncoming.chain_ok.is_not(None))
                .distinct(P2PIncoming.card_last4)
                .order_by(P2PIncoming.card_last4, P2PIncoming.received_at.desc())
            )
        ).all()
    }
    return matched, last_at, chain


def _card_out(
    c: P2PCard,
    matched: dict[str, int],
    last_at: dict[str, datetime],
    chain: dict[str, bool],
) -> P2PCardAdminOut:
    return P2PCardAdminOut(
        id=c.id,
        label=c.label,
        pan_last4=c.pan_last4,
        holder_name=c.holder_name,
        network=c.network,
        active=c.active,
        min_amount_uzs=c.min_amount_uzs,
        max_amount_uzs=c.max_amount_uzs,
        daily_limit_uzs=c.daily_limit_uzs,
        matched_today_uzs=matched.get(c.id, 0),
        last_incoming_at=last_at.get(c.pan_last4),
        chain_ok_last=chain.get(c.pan_last4),
    )


async def _one_card_out(db: AsyncSession, c: P2PCard) -> P2PCardAdminOut:
    return _card_out(c, *await _card_stats(db, [c]))


@router.get("/cards", response_model=list[P2PCardAdminOut], summary="P2P cards")
async def list_cards(db: Db) -> list[P2PCardAdminOut]:
    """Every card with today's matched total and its receive health."""
    cards = list((await db.execute(select(P2PCard).order_by(P2PCard.created_at))).scalars().all())
    stats = await _card_stats(db, cards)
    return [_card_out(c, *stats) for c in cards]


@router.post(
    "/cards",
    response_model=P2PCardAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a P2P card",
)
async def create_card(
    body: P2PCardCreateIn, db: Db, admin: Admin, idempotency_key: IdempotencyKeyHeader = None
) -> P2PCardAdminOut:
    """Seal the number and store the card. The number is never returned."""
    key = normalize_idempotency_key(idempotency_key)
    if (
        hit := await replayed(db, scope="p2p.card.create", key=key, model=P2PCardAdminOut)
    ) is not None:
        return hit
    pan = normalize_pan(body.pan)
    _check_bounds(body.min_amount_uzs, body.max_amount_uzs)
    ct, nonce = seal_pan(pan)
    card = P2PCard(
        id=new_id(),
        label=body.label,
        pan_ciphertext=ct,
        pan_nonce=nonce,
        pan_last4=pan[-4:],
        holder_name=body.holder_name,
        network=body.network,
        active=body.active,
        min_amount_uzs=body.min_amount_uzs,
        max_amount_uzs=body.max_amount_uzs,
        daily_limit_uzs=body.daily_limit_uzs,
        updated_by=admin.id,
    )
    db.add(card)
    await db.flush()
    await db.refresh(card)
    out = await _one_card_out(db, card)
    log.info(
        "p2p.card_saved",
        admin_id=admin.id,
        changed=sorted(body.model_fields_set),
        card_last4=card.pan_last4,
        created=True,
    )
    await remember(
        db,
        scope="p2p.card.create",
        key=key,
        body=out.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    await db.commit()
    return out


def _check_bounds(min_uzs: int, max_uzs: int) -> None:
    if min_uzs <= 0 or max_uzs < min_uzs:
        raise ValidationError("max amount must be at least the min amount", code="p2p_bounds")


@router.patch("/cards/{card_id}", response_model=P2PCardAdminOut, summary="Edit a P2P card")
async def patch_card(
    card_id: str,
    body: P2PCardPatchIn,
    db: Db,
    admin: Admin,
    idempotency_key: IdempotencyKeyHeader = None,
) -> P2PCardAdminOut:
    """Apply the fields present; ``pan`` re-seals the number and updates the last four."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"p2p.card.patch.{card_id}"
    if (hit := await replayed(db, scope=scope, key=key, model=P2PCardAdminOut)) is not None:
        return hit
    card = await _load_card(db, card_id)
    sent = body.model_fields_set
    if body.pan is not None:
        pan = normalize_pan(body.pan)
        card.pan_ciphertext, card.pan_nonce = seal_pan(pan)
        card.pan_last4 = pan[-4:]
    for field in ("label", "holder_name", "network", "min_amount_uzs", "max_amount_uzs", "active"):
        value = getattr(body, field)
        if value is not None:
            setattr(card, field, value)
    if "daily_limit_uzs" in sent:
        card.daily_limit_uzs = body.daily_limit_uzs
    _check_bounds(card.min_amount_uzs, card.max_amount_uzs)
    card.updated_by = admin.id
    card.updated_at = now()
    await db.flush()
    out = await _one_card_out(db, card)
    log.info(
        "p2p.card_saved",
        admin_id=admin.id,
        changed=sorted(sent),
        card_last4=card.pan_last4,
        created=False,
    )
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _load_card(db: AsyncSession, card_id: str) -> P2PCard:
    key = parse_uuid(card_id)
    card = await db.get(P2PCard, key) if key else None
    if card is None:
        raise NotFoundError("card not found", code="p2p_card_not_found")
    return card


__all__ = ["router"]
