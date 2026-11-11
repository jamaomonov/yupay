"""Admin routes for USDT top-ups: the switch row, the chain journal, reservations (ADR-0104)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select

from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.logging import get_logger
from yupay.modules.admin.deps import require_admin
from yupay.modules.merchants import transactions
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.p2p.admin_deps import Admin, Db, PageLimit, parse_uuid
from yupay.modules.usdt import resolve
from yupay.modules.usdt.models import UsdtIncoming, UsdtReservation, UsdtSettings
from yupay.modules.usdt.schemas import (
    UsdtCreditIn,
    UsdtDismissIn,
    UsdtIncomingOut,
    UsdtIncomingPageOut,
    UsdtNetworkCode,
    UsdtNetworkIn,
    UsdtNetworkOut,
    UsdtReservationAdminOut,
    UsdtReservationPageOut,
    UsdtResult,
    UsdtSettingsIn,
    UsdtSettingsOut,
)
from yupay.modules.usdt.settings import load_networks, load_settings

router = APIRouter(prefix="/admin/usdt", tags=["admin:usdt"], dependencies=[Depends(require_admin)])
log = get_logger("yupay.usdt.admin")


async def _settings_out(db: Db, s: UsdtSettings) -> UsdtSettingsOut:
    return UsdtSettingsOut(
        mode=s.mode,  # type: ignore[arg-type]  # the check constraint pins it
        allowlist_merchant_ids=s.allowlist_merchant_ids,
        min_amount_usd=s.min_amount_usd,
        max_amount_usd=s.max_amount_usd,
        updated_at=s.updated_at,
        networks=[
            UsdtNetworkOut.model_validate(n, from_attributes=True) for n in await load_networks(db)
        ],
    )


@router.get("/settings", response_model=UsdtSettingsOut, summary="USDT switches")
async def get_usdt_settings(db: Db) -> UsdtSettingsOut:
    """Mode, allowlist, amount bounds, and every chain's address and switch."""
    out = await _settings_out(db, await load_settings(db))
    await db.commit()  # load_* create the rows on a fresh database
    return out


async def _checked_allowlist(db: Db, ids_in: list[str]) -> list[str]:
    ids = list(dict.fromkeys(ids_in))
    bad = [i for i in ids if parse_uuid(i) is None]
    ids = [i for i in ids if parse_uuid(i) is not None]
    known = set((await db.execute(select(Merchant.id).where(Merchant.id.in_(ids)))).scalars())
    if unknown := bad + [i for i in ids if i not in known]:
        raise ValidationError(
            "unknown merchant in allowlist", code="usdt_unknown_merchant", merchant_ids=unknown
        )
    return ids


@router.patch("/settings", response_model=UsdtSettingsOut, summary="Change USDT switches")
async def patch_usdt_settings(
    body: UsdtSettingsIn, db: Db, admin: Admin, idempotency_key: IdempotencyKeyHeader = None
) -> UsdtSettingsOut:
    """Apply the fields present in the body. Chains are changed one by one."""
    key = normalize_idempotency_key(idempotency_key)
    if (
        hit := await replayed(db, scope="usdt.settings", key=key, model=UsdtSettingsOut)
    ) is not None:
        return hit
    s = await load_settings(db)
    sent = body.model_fields_set
    if body.mode is not None:
        s.mode = body.mode
    if body.allowlist_merchant_ids is not None:
        s.allowlist_merchant_ids = await _checked_allowlist(db, body.allowlist_merchant_ids)
    lo = body.min_amount_usd if body.min_amount_usd is not None else s.min_amount_usd
    hi = body.max_amount_usd if body.max_amount_usd is not None else s.max_amount_usd
    if hi < lo:
        raise ValidationError("max is below min", code="usdt_bad_bounds")
    s.min_amount_usd, s.max_amount_usd = lo, hi
    s.updated_by, s.updated_at = admin.id, now()
    await db.flush()
    out = await _settings_out(db, s)
    log.info("usdt.settings_saved", admin_id=admin.id, changed=sorted(sent), mode=s.mode)
    await remember(db, scope="usdt.settings", key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.patch("/networks/{network}", response_model=UsdtSettingsOut, summary="Change one chain")
async def patch_usdt_network(
    network: UsdtNetworkCode,
    body: UsdtNetworkIn,
    db: Db,
    admin: Admin,
    idempotency_key: IdempotencyKeyHeader = None,
) -> UsdtSettingsOut:
    """Switch a chain on or off, or set its receiving address.

    A new address restarts that chain's poll at now and closes its pending
    reservations (``resolve.change_address``).
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"usdt.network.{network}"
    if (hit := await replayed(db, scope=scope, key=key, model=UsdtSettingsOut)) is not None:
        return hit
    rows = {n.network: n for n in await load_networks(db)}
    n = rows[network]
    sent = body.model_fields_set
    if "address" in sent:
        await resolve.change_address(db, n, body.address)
    if body.enabled is not None:
        n.enabled = body.enabled
    n.updated_by, n.updated_at = admin.id, now()
    await db.flush()
    out = await _settings_out(db, await load_settings(db))
    log.info("usdt.network_saved", admin_id=admin.id, network=network, changed=sorted(sent))
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


def _joined() -> Select[Any]:  # outer-joined columns: SQLAlchemy cannot type them
    return (
        select(UsdtIncoming, UsdtReservation.number, Merchant.title, Merchant.id)
        .outerjoin(UsdtReservation, UsdtReservation.id == UsdtIncoming.reservation_id)
        # The reseller: the reservation's, else the one credited by hand.
        .outerjoin(
            Merchant,
            Merchant.id == func.coalesce(UsdtReservation.merchant_id, UsdtIncoming.merchant_id),
        )
    )


def _incoming_out(
    row: UsdtIncoming, number: str | None, title: str | None, merchant_id: str | None
) -> UsdtIncomingOut:
    return UsdtIncomingOut(
        id=row.id,
        network=row.network,  # type: ignore[arg-type]  # the check constraint pins it
        tx_id=row.tx_id,
        from_address=row.from_address,
        amount_usdt=row.amount_usdt,
        block_at=row.block_at,
        received_at=row.received_at,
        result=row.result,  # type: ignore[arg-type]  # the check constraint pins the values
        reservation_number=number,
        merchant_id=merchant_id,
        merchant_title=title,
        note=row.note,
        resolved_at=row.resolved_at,
    )


@router.get("/incoming", response_model=UsdtIncomingPageOut, summary="USDT transfer journal")
async def list_incoming(
    db: Db,
    result: Annotated[UsdtResult | None, Query()] = None,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> UsdtIncomingPageOut:
    """Newest first by block time, keyset-paged; filter by ``result``."""
    stmt = _joined()
    if result is not None:
        stmt = stmt.where(UsdtIncoming.result == result)
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (UsdtIncoming.block_at < at) | ((UsdtIncoming.block_at == at) & (UsdtIncoming.id < rid))
        )
    rows = (
        await db.execute(
            stmt.order_by(UsdtIncoming.block_at.desc(), UsdtIncoming.id.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    nxt = (
        transactions.encode_cursor(page[-1][0].block_at, page[-1][0].id)
        if len(rows) > limit
        else None
    )
    return UsdtIncomingPageOut(
        items=[_incoming_out(r, n, t, m) for r, n, t, m in page], next_cursor=nxt
    )


async def _one_out(db: Db, row: UsdtIncoming) -> UsdtIncomingOut:
    found = (await db.execute(_joined().where(UsdtIncoming.id == row.id))).one()
    return _incoming_out(found[0], found[1], found[2], found[3])


@router.post(
    "/incoming/{incoming_id}/credit",
    response_model=UsdtIncomingOut,
    summary="Credit an unmatched transfer to a reseller",
)
async def credit_incoming(
    incoming_id: str,
    body: UsdtCreditIn,
    db: Db,
    admin: Admin,
    idempotency_key: IdempotencyKeyHeader = None,  # noqa: ARG001 - idempotent by state + ledger key
) -> UsdtIncomingOut:
    """Book the transfer's amount (rounded down to cents) on the reseller's deposit.

    Idempotent by state: a row already credited to the same reseller is returned
    as is, and the ledger key ``usdt:incoming:{id}`` makes a racing twin a replay.
    """
    row = await resolve.credit(
        db,
        incoming_id=incoming_id,
        merchant_id=body.merchant_id,
        note=body.note,
        admin_id=admin.id,
    )
    out = await _one_out(db, row)
    await db.commit()
    return out


@router.post(
    "/incoming/{incoming_id}/dismiss",
    response_model=UsdtIncomingOut,
    summary="Close an unmatched transfer without crediting",
)
async def dismiss_incoming(
    incoming_id: str,
    body: UsdtDismissIn,
    db: Db,
    admin: Admin,
    idempotency_key: IdempotencyKeyHeader = None,  # noqa: ARG001 - idempotent by state
) -> UsdtIncomingOut:
    """Mark an unmatched transfer handled outside the system (refunded, not a top-up)."""
    row = await resolve.dismiss(db, incoming_id=incoming_id, note=body.note, admin_id=admin.id)
    out = await _one_out(db, row)
    await db.commit()
    return out


@router.get(
    "/reservations", response_model=UsdtReservationPageOut, summary="USDT top-up reservations"
)
async def list_reservations(
    db: Db, cursor: str | None = None, limit: PageLimit = 50
) -> UsdtReservationPageOut:
    """Newest first, keyset-paged."""
    stmt = select(UsdtReservation, Merchant.title).outerjoin(
        Merchant, Merchant.id == UsdtReservation.merchant_id
    )
    if cursor:
        at, rid = transactions.decode_cursor(cursor)
        stmt = stmt.where(
            (UsdtReservation.created_at < at)
            | ((UsdtReservation.created_at == at) & (UsdtReservation.id < rid))
        )
    rows = (
        await db.execute(
            stmt.order_by(UsdtReservation.created_at.desc(), UsdtReservation.id.desc()).limit(
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
    return UsdtReservationPageOut(
        items=[
            UsdtReservationAdminOut(
                number=r.number,
                merchant_id=r.merchant_id,
                merchant_title=title,
                network=r.network,
                amount=r.amount_usdt,
                status=r.status,
                created_at=r.created_at,
                expires_at=r.expires_at,
                closed_at=r.closed_at,
            )
            for r, title in page
        ],
        next_cursor=nxt,
    )


__all__ = ["router"]
