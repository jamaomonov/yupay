"""Admin routes for the P2P incoming journal and the reservation list."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select

from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.merchants import transactions
from yupay.modules.merchants.models import Merchant
from yupay.modules.p2p.admin_deps import Db, PageLimit, parse_uuid
from yupay.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from yupay.modules.p2p.schemas import (
    P2PIncomingDetailOut,
    P2PIncomingOut,
    P2PIncomingPageOut,
    P2PIncomingReservationOut,
    P2PReservationAdminOut,
    P2PReservationPageOut,
)

router = APIRouter()

_AMOUNT_CEILING = Decimal(10) ** 15


def _amount_filter(
    amount: Annotated[
        str | None,
        Query(max_length=20, description="Exact soʻm amount, at most 2 decimals, e.g. 50000.00"),
    ] = None,
) -> Decimal | None:
    """Parse the journal's ``amount`` filter.

    Raises:
        ValidationError: ``p2p_amount_invalid`` for text, NaN, infinities,
            negatives, more than two decimals or an absurd magnitude.
    """
    if amount is None or amount == "":
        return None
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValidationError("amount must be a number", code="p2p_amount_invalid") from exc
    exponent = value.as_tuple().exponent
    if (
        not value.is_finite()
        or value < 0
        or value >= _AMOUNT_CEILING
        or not isinstance(exponent, int)
        or exponent < -2
    ):
        raise ValidationError(
            "amount must be a non-negative number with at most 2 decimals",
            code="p2p_amount_invalid",
        )
    return value


AmountFilter = Annotated[Decimal | None, Depends(_amount_filter)]


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
    amount: AmountFilter,
    card_last4: Annotated[str | None, Query(min_length=4, max_length=4)] = None,
    kind: Annotated[str | None, Query(pattern="^(credit|debit|unparsed)$")] = None,
    result: Annotated[str | None, Query(pattern="^(matched|unmatched|ignored)$")] = None,
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
    if amount is not None:
        stmt = stmt.where(P2PIncoming.amount_uzs == amount)
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
        if (uid := parse_uuid(incoming_id))
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
        if (mid := parse_uuid(merchant_id)) is None:
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
