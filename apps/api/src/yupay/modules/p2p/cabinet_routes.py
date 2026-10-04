"""Reseller self-serve top-up by P2P card transfer (spec §5.3, §6)."""

from __future__ import annotations

from fastapi import APIRouter, status

from yupay.core.clock import now
from yupay.core.idempotency import normalize_idempotency_key
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader
from yupay.modules.p2p import reservations
from yupay.modules.p2p.cards import open_pan
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.p2p.schemas import (
    P2PCardDetailsOut,
    P2PDepositIn,
    P2PDepositOut,
    P2PDepositsOut,
    P2PStatusOut,
)
from yupay.modules.p2p.settings import admits, load_settings
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate

router = APIRouter(prefix="/merchant/cabinet/p2p", tags=["merchant-cabinet"])


def _grouped(pan: str) -> str:
    return " ".join(pan[i : i + 4] for i in range(0, len(pan), 4))


async def _out(db: Db, r: P2PReservation, *, with_card: bool) -> P2PDepositOut:
    card: P2PCardDetailsOut | None = None
    if with_card and r.status == "pending" and r.expires_at > now():
        c = await db.get(P2PCard, r.card_id)
        if c is not None:
            card = P2PCardDetailsOut(
                pan=_grouped(open_pan(c)), holder_name=c.holder_name, network=c.network
            )
    return P2PDepositOut(
        number=r.number,
        status=r.status,
        amount_uzs=r.amount_uzs,
        amount_usd=r.amount_usd,
        fx_rate=str(r.fx_rate),
        created_at=r.created_at,
        expires_at=r.expires_at,
        closed_at=r.closed_at,
        card=card,
    )


@router.get("/status", response_model=P2PStatusOut, summary="Whether P2P top-up is on for me")
async def p2p_status(user: CurrentUser, db: Db) -> P2PStatusOut:
    """The switch for showing "Top up", plus the guarded USD→UZS rate for the preview."""
    merchant = await merchant_of(db, user)
    enabled = admits(await load_settings(db), merchant.id)
    rate: str | None = None
    if enabled:
        try:
            rate = str(await guarded_usd_rate(db, quote="UZS"))
        except RateRejected:
            rate = None
    await db.commit()  # guarded_usd_rate may have written an fx_snapshots row
    return P2PStatusOut(enabled=enabled, fx_rate=rate)


@router.post(
    "/deposits",
    response_model=P2PDepositOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve an exact amount to transfer",
)
async def create_deposit(
    body: P2PDepositIn,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> P2PDepositOut:
    """Hold an exact amount for five minutes; races resolve inside the service."""
    merchant = await merchant_of(db, user)
    r = await reservations.reserve(
        db,
        merchant_id=merchant.id,
        amount_uzs=body.amount_uzs,
        idempotency_key=normalize_idempotency_key(idempotency_key),
    )
    out = await _out(db, r, with_card=True)
    await db.commit()
    return out


@router.get("/deposits/{number}", response_model=P2PDepositOut, summary="One top-up")
async def read_deposit(number: str, user: CurrentUser, db: Db) -> P2PDepositOut:
    """Poll one top-up; a stale pending one is reported as expired."""
    merchant = await merchant_of(db, user)
    r = await reservations.read(db, merchant_id=merchant.id, number=number)
    out = await _out(db, r, with_card=True)
    await db.commit()
    return out


@router.post(
    "/deposits/{number}/cancel",
    response_model=P2PDepositOut,
    summary="Cancel a waiting top-up",
)
async def cancel_deposit(
    number: str,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,  # noqa: ARG001 - accepted per AGENTS.md §9
) -> P2PDepositOut:
    """Cancel a pending top-up.

    The ``Idempotency-Key`` header is accepted but unused: the operation is
    idempotent by state, so cancelling a cancelled top-up returns it unchanged.
    """
    merchant = await merchant_of(db, user)
    r = await reservations.cancel(db, merchant_id=merchant.id, number=number)
    out = await _out(db, r, with_card=False)
    await db.commit()
    return out


@router.get("/deposits", response_model=P2PDepositsOut, summary="My top-ups")
async def list_deposits(
    user: CurrentUser, db: Db, cursor: str | None = None, limit: int = 25
) -> P2PDepositsOut:
    """Newest first, keyset-paged; items never carry the card."""
    merchant = await merchant_of(db, user)
    rows, nxt = await reservations.list_for_merchant(
        db, merchant_id=merchant.id, limit=max(1, min(limit, 100)), cursor=cursor
    )
    return P2PDepositsOut(items=[await _out(db, r, with_card=False) for r in rows], next_cursor=nxt)
