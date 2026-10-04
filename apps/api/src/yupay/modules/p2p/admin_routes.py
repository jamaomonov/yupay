"""Admin routes for P2P top-ups: switches, cards, the incoming journal, reservations."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.admin.deps import require_admin
from yupay.modules.merchants import transactions
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.p2p.cards import normalize_pan, seal_pan
from yupay.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from yupay.modules.p2p.parsing import TASHKENT
from yupay.modules.p2p.schemas import (
    P2PCardAdminOut,
    P2PCardCreateIn,
    P2PCardPatchIn,
    P2PIncomingDetailOut,
    P2PIncomingOut,
    P2PIncomingPageOut,
    P2PIncomingReservationOut,
    P2PReservationAdminOut,
    P2PReservationPageOut,
    P2PSettingsIn,
    P2PSettingsOut,
)
from yupay.modules.p2p.settings import load_settings
from yupay.modules.users.models import User

router = APIRouter(
    prefix="/admin/p2p",
    tags=["admin:p2p"],
    dependencies=[Depends(require_admin)],
)

log = get_logger("yupay.p2p.admin")

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def _settings_out(s: object) -> P2PSettingsOut:
    return P2PSettingsOut.model_validate(s, from_attributes=True)


@router.get("/settings", response_model=P2PSettingsOut, summary="P2P switches")
async def get_p2p_settings(db: Db) -> P2PSettingsOut:
    """Current mode, allowlist and the HUMO bot's Telegram id."""
    out = _settings_out(await load_settings(db))
    await db.commit()  # load_settings creates the row on a fresh database
    return out


@router.patch("/settings", response_model=P2PSettingsOut, summary="Change P2P switches")
async def patch_p2p_settings(
    body: P2PSettingsIn, db: Db, admin: Admin, idempotency_key: IdempotencyKeyHeader = None
) -> P2PSettingsOut:
    """Apply the fields present in the body; ``humo_bot_user_id: null`` clears it."""
    key = normalize_idempotency_key(idempotency_key)
    if (hit := await replayed(db, scope="p2p.settings", key=key, model=P2PSettingsOut)) is not None:
        return hit
    s = await load_settings(db)
    sent = body.model_fields_set
    if body.mode is not None:
        s.mode = body.mode
    if body.allowlist_merchant_ids is not None:
        ids = list(dict.fromkeys(body.allowlist_merchant_ids))
        bad = [i for i in ids if _uuid(i) is None]
        ids = [i for i in ids if _uuid(i) is not None]
        known = set(
            (await db.execute(select(Merchant.id).where(Merchant.id.in_(ids)))).scalars().all()
        )
        if unknown := bad + [i for i in ids if i not in known]:
            raise ValidationError(
                "unknown merchant in allowlist", code="p2p_unknown_merchant", merchant_ids=unknown
            )
        s.allowlist_merchant_ids = ids
    if "humo_bot_user_id" in sent:
        s.humo_bot_user_id = body.humo_bot_user_id
    s.updated_by = admin.id
    s.updated_at = now()
    await db.flush()
    out = _settings_out(s)
    log.info("p2p.settings_saved", mode=s.mode, allowlist_size=len(s.allowlist_merchant_ids))
    await remember(db, scope="p2p.settings", key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _card_stats(
    db: AsyncSession, cards: list[P2PCard]
) -> tuple[dict[str, int], dict[str, datetime], dict[str, bool]]:
    """Today's matched total per card id, plus last notification and chain verdict per last4."""
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
    log.info("p2p.card_saved", card_last4=card.pan_last4, created=True)
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
    log.info("p2p.card_saved", card_last4=card.pan_last4, created=False)
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


def _uuid(value: str) -> str | None:
    """Canonical uuid text, or ``None`` so a malformed path id is a 404 and not a DB error."""
    try:
        return str(UUID(value))
    except ValueError:
        return None


async def _load_card(db: AsyncSession, card_id: str) -> P2PCard:
    card = await db.get(P2PCard, _uuid(card_id)) if _uuid(card_id) else None
    if card is None:
        raise NotFoundError("card not found", code="p2p_card_not_found")
    return card


def _incoming_out(
    row: P2PIncoming,
    number: str | None,
    merchant_id: str | None,
    amount_usd: Decimal | None,
    title: str | None,
    *,
    detail: bool = False,
) -> P2PIncomingOut:
    reservation = (
        P2PIncomingReservationOut(
            number=number, merchant_id=merchant_id, merchant_title=title, amount_usd=amount_usd
        )
        if number is not None and amount_usd is not None
        else None
    )
    model = P2PIncomingDetailOut if detail else P2PIncomingOut
    return model.model_validate(row, from_attributes=True).model_copy(
        update={"reservation": reservation}
    )


def _joined_incoming() -> Select[Any]:  # outer-joined columns: SQLAlchemy cannot type them
    return (
        select(
            P2PIncoming,
            P2PReservation.number,
            P2PReservation.merchant_id,
            P2PReservation.amount_usd,
            Merchant.title,
        )
        .select_from(P2PIncoming)
        .outerjoin(P2PReservation, P2PReservation.id == P2PIncoming.reservation_id)
        .outerjoin(Merchant, Merchant.id == P2PReservation.merchant_id)
    )


@router.get("/incoming", response_model=P2PIncomingPageOut, summary="Incoming transfer journal")
async def list_incoming(
    db: Db,
    card_last4: Annotated[str | None, Query(min_length=4, max_length=4)] = None,
    kind: Annotated[str | None, Query(pattern="^(credit|debit|unparsed)$")] = None,
    result: Annotated[str | None, Query(pattern="^(matched|unmatched|ignored)$")] = None,
    amount: Annotated[str | None, Query(max_length=20)] = None,
    cursor: str | None = None,
    limit: PageLimit = 25,
) -> P2PIncomingPageOut:
    """Newest first. Notification text is deliberately absent; see the detail route."""
    stmt = _joined_incoming()
    if card_last4:
        stmt = stmt.where(P2PIncoming.card_last4 == card_last4)
    if kind:
        stmt = stmt.where(P2PIncoming.kind == kind)
    if result:
        stmt = stmt.where(P2PIncoming.result == result)
    if amount:
        try:
            stmt = stmt.where(P2PIncoming.amount_uzs == Decimal(amount))
        except InvalidOperation as exc:
            raise ValidationError("amount must be a number", code="p2p_amount_invalid") from exc
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (P2PIncoming.received_at < at)
            | ((P2PIncoming.received_at == at) & (P2PIncoming.id < rid))
        )
    rows = (
        await db.execute(
            stmt.order_by(P2PIncoming.received_at.desc(), P2PIncoming.id.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    nxt = (
        transactions.encode_cursor(page[-1][0].received_at, page[-1][0].id)
        if len(rows) > limit
        else None
    )
    return P2PIncomingPageOut(items=[_incoming_out(*r) for r in page], next_cursor=nxt)


@router.get(
    "/incoming/{incoming_id}",
    response_model=P2PIncomingDetailOut,
    summary="One journal row with its raw notification text",
)
async def get_incoming(incoming_id: str, db: Db) -> P2PIncomingDetailOut:
    """The only route that returns ``raw_text`` (PII: balances and counterparties)."""
    row = (
        (await db.execute(_joined_incoming().where(P2PIncoming.id == uid))).first()
        if (uid := _uuid(incoming_id))
        else None
    )
    if row is None:
        raise NotFoundError("incoming row not found", code="p2p_incoming_not_found")
    out = _incoming_out(*row, detail=True)
    assert isinstance(out, P2PIncomingDetailOut)
    return out


@router.get(
    "/reservations", response_model=P2PReservationPageOut, summary="P2P top-up reservations"
)
async def list_reservations(
    db: Db,
    status_: Annotated[
        str | None, Query(alias="status", pattern="^(pending|paid|expired|cancelled)$")
    ] = None,
    merchant_id: str | None = None,
    cursor: str | None = None,
    limit: PageLimit = 25,
) -> P2PReservationPageOut:
    """Newest first, with the merchant's title from a single join."""
    stmt = (
        select(P2PReservation, Merchant.title, P2PCard.pan_last4)
        .join(P2PCard, P2PCard.id == P2PReservation.card_id)
        .outerjoin(Merchant, Merchant.id == P2PReservation.merchant_id)
    )
    if status_:
        stmt = stmt.where(P2PReservation.status == status_)
    if merchant_id:
        if (mid := _uuid(merchant_id)) is None:
            raise ValidationError("merchant_id must be a uuid", code="p2p_bad_id")
        stmt = stmt.where(P2PReservation.merchant_id == mid)
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (P2PReservation.created_at < at)
            | ((P2PReservation.created_at == at) & (P2PReservation.id < rid))
        )
    rows = (
        await db.execute(
            stmt.order_by(P2PReservation.created_at.desc(), P2PReservation.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    page = rows[:limit]
    nxt = (
        transactions.encode_cursor(page[-1][0].created_at, page[-1][0].id)
        if len(rows) > limit
        else None
    )
    items = [
        P2PReservationAdminOut(
            number=r.number,
            merchant_id=r.merchant_id,
            merchant_title=title,
            card_last4=last4,
            amount_uzs=r.amount_uzs,
            amount_usd=r.amount_usd,
            status=r.status,
            created_at=r.created_at,
            expires_at=r.expires_at,
            closed_at=r.closed_at,
        )
        for r, title, last4 in page
    ]
    return P2PReservationPageOut(items=items, next_cursor=nxt)


__all__ = ["router"]
