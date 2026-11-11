"""Reseller self-serve top-up by USDT (TRC20) transfer (ADR-0104)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from yupay.core.clock import now
from yupay.core.idempotency import normalize_idempotency_key
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader
from yupay.modules.usdt import reservations
from yupay.modules.usdt.models import UsdtIncoming, UsdtReservation
from yupay.modules.usdt.schemas import (
    UsdtDepositIn,
    UsdtDepositOut,
    UsdtDepositsOut,
    UsdtStatusOut,
)
from yupay.modules.usdt.settings import admits, load_settings

router = APIRouter(prefix="/merchant/cabinet/usdt", tags=["merchant-cabinet"])


async def _tx_ids(db: Db, rows: list[UsdtReservation]) -> dict[str, str]:
    """The paying transaction of each paid row, in one query (no N+1 on the list)."""
    ids = [r.incoming_id for r in rows if r.incoming_id is not None]
    if not ids:
        return {}
    found = await db.execute(
        select(UsdtIncoming.id, UsdtIncoming.tx_id).where(UsdtIncoming.id.in_(ids))
    )
    return dict(found.tuples().all())


def _build(r: UsdtReservation, tx_ids: dict[str, str], *, with_address: bool) -> UsdtDepositOut:
    tx_id = tx_ids.get(r.incoming_id) if r.incoming_id is not None else None
    show = with_address and r.status == "pending" and r.expires_at > now()
    return UsdtDepositOut(
        number=r.number,
        status=r.status,
        amount=r.amount_usdt,
        address=r.address if show else None,
        created_at=r.created_at,
        expires_at=r.expires_at,
        closed_at=r.closed_at,
        tx_id=tx_id,
    )


async def _out(db: Db, r: UsdtReservation, *, with_address: bool) -> UsdtDepositOut:
    return _build(r, await _tx_ids(db, [r]), with_address=with_address)


@router.get("/status", response_model=UsdtStatusOut, summary="Whether USDT top-up is on for me")
async def usdt_status(user: CurrentUser, db: Db) -> UsdtStatusOut:
    """The switch for showing the USDT method, with the amount bounds."""
    merchant = await merchant_of(db, user)
    s = await load_settings(db)
    enabled = admits(s, merchant.id)
    await db.commit()  # load_settings creates the row on a fresh database
    return UsdtStatusOut(
        enabled=enabled,
        min_amount=s.min_amount_usd if enabled else None,
        max_amount=s.max_amount_usd if enabled else None,
    )


@router.post(
    "/deposits",
    response_model=UsdtDepositOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve an exact USDT amount to send",
)
async def create_deposit(
    body: UsdtDepositIn,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> UsdtDepositOut:
    """Hold an exact amount for 30 minutes; races resolve inside the service."""
    merchant = await merchant_of(db, user)
    r = await reservations.reserve(
        db,
        merchant_id=merchant.id,
        amount=body.amount,
        idempotency_key=normalize_idempotency_key(idempotency_key),
    )
    out = await _out(db, r, with_address=True)
    await db.commit()
    return out


@router.get("/deposits/{number}", response_model=UsdtDepositOut, summary="One USDT top-up")
async def read_deposit(number: str, user: CurrentUser, db: Db) -> UsdtDepositOut:
    """Poll one top-up; a stale pending one is reported as expired."""
    merchant = await merchant_of(db, user)
    r = await reservations.read(db, merchant_id=merchant.id, number=number)
    out = await _out(db, r, with_address=True)
    await db.commit()
    return out


@router.post(
    "/deposits/{number}/cancel",
    response_model=UsdtDepositOut,
    summary="Cancel a waiting USDT top-up",
)
async def cancel_deposit(
    number: str,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,  # noqa: ARG001 - accepted per AGENTS.md §9
) -> UsdtDepositOut:
    """Cancel a pending top-up.

    The ``Idempotency-Key`` header is accepted but unused: the operation is
    idempotent by state, so cancelling a cancelled top-up returns it unchanged.
    A transfer already sent still pays it (matching is by block time).
    """
    merchant = await merchant_of(db, user)
    r = await reservations.cancel(db, merchant_id=merchant.id, number=number)
    out = await _out(db, r, with_address=False)
    await db.commit()
    return out


@router.get("/deposits", response_model=UsdtDepositsOut, summary="My USDT top-ups")
async def list_deposits(
    user: CurrentUser,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> UsdtDepositsOut:
    """Newest first, keyset-paged; items never carry the address."""
    merchant = await merchant_of(db, user)
    rows, nxt = await reservations.list_for_merchant(
        db, merchant_id=merchant.id, limit=limit, cursor=cursor
    )
    tx_ids = await _tx_ids(db, rows)
    return UsdtDepositsOut(
        items=[_build(r, tx_ids, with_address=False) for r in rows], next_cursor=nxt
    )


__all__ = ["router"]
