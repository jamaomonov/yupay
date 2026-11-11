"""Operator actions on USDT top-up: settings changes and unmatched-transfer resolution.

The money rules live here, not in ``admin_routes`` (AGENTS.md §6): which
journal rows may be credited, how much, under which ledger key, and what an
address change does to reservations already showing the old address.
"""

from __future__ import annotations

from decimal import ROUND_DOWN
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.merchants.deposit import credit_deposit
from yupay.modules.merchants.models import Merchant
from yupay.modules.p2p.admin_deps import parse_uuid
from yupay.modules.usdt.address import is_address
from yupay.modules.usdt.models import UsdtIncoming, UsdtNetwork, UsdtReservation
from yupay.modules.usdt.networks import NETWORKS
from yupay.modules.usdt.reservations import CENT, QUARANTINE

log = get_logger("yupay.usdt.resolve")

_RESOLVED: Final = "this transfer is already resolved"


async def change_address(db: AsyncSession, n: UsdtNetwork, raw: str | None) -> str | None:
    """Point one chain's top-ups at a new address (or none).

    The checksum is checked for the chain's kind. The cursor is cleared, so
    the poller starts that chain at "now" and never reads the new address's
    earlier history. Every pending reservation **on this chain** is closed:
    those show the old address, which the poller no longer reads, and leaving
    them open kept a reseller paying into an address nobody watched. A
    transfer already sent to the old one is reconciled by hand (runbook §4).

    Returns:
        The alert text for the caller to send after commit (the one setting
        that redirects every reseller's money must never change silently), or
        ``None`` when nothing changed.

    Raises:
        ValidationError: ``usdt_bad_address`` when the checksum fails.
    """
    address = (raw or "").strip() or None
    if address is not None and not is_address(NETWORKS[n.network].kind, address):
        raise ValidationError("not a valid address for this network", code="usdt_bad_address")
    if address == n.address:
        return None
    old, at = n.address, now()
    closed = await db.execute(
        update(UsdtReservation)
        .where(UsdtReservation.status == "pending", UsdtReservation.network == n.network)
        .values(status="expired", closed_at=at, quarantine_until=at + QUARANTINE)
    )
    n.address, n.cursor, n.cursor_exact = address, None, False
    count = getattr(closed, "rowcount", 0) or 0
    log.info("usdt.address_changed", network=n.network, closed_pending=count)
    return (
        f"USDT ({n.network.upper()}): адрес приёма изменён\n{old or '—'} → {address or '—'}\n"
        f"Закрыто ожидающих пополнений: {count}. Переводы на старый адрес больше не "
        "читаются — проверьте его в обозревателе и зачислите вручную. "
        "Если меняли не вы — немедленно выключите сеть."
    )


async def reenable(db: AsyncSession, n: UsdtNetwork, enabled: bool) -> None:
    """Switch a chain; turning it back on after a pause restarts it at "now".

    A chain with nothing held is not read while off, so its cursor stays where
    it stopped. Resuming from there would journal — and page the urgent chat
    for — every transfer the address received meanwhile, none of them top-ups.
    While anything is still held the chain was being read, so it keeps going.
    """
    if enabled and not n.enabled:
        held = await db.scalar(
            select(func.count())
            .select_from(UsdtReservation)
            .where(UsdtReservation.network == n.network, UsdtReservation.holds_amount.is_(True))
        )
        if not held:
            n.cursor, n.cursor_exact = None, False
    n.enabled = enabled


async def _locked(db: AsyncSession, incoming_id: str) -> UsdtIncoming:
    rid = parse_uuid(incoming_id)
    row: UsdtIncoming | None = (
        await db.scalar(select(UsdtIncoming).where(UsdtIncoming.id == rid).with_for_update())
        if rid
        else None
    )
    if row is None:
        raise NotFoundError("transfer not found", code="usdt_incoming_not_found")
    return row


async def credit(
    db: AsyncSession, *, incoming_id: str, merchant_id: str, note: str | None, admin_id: str
) -> UsdtIncoming:
    """Credit an unmatched transfer to a reseller: amount rounded down to cents.

    Idempotent by state — the row already credited to the same reseller comes
    back as is — and by the ledger key ``usdt:incoming:{id}``. Only
    ``unmatched`` rows can be credited: a matched one already paid a
    reservation, and crediting it again would pay twice.

    Raises:
        NotFoundError: The transfer or the merchant does not exist.
        ConflictError: ``usdt_incoming_resolved`` for any other resolved row.
    """
    row = await _locked(db, incoming_id)
    target = parse_uuid(merchant_id)
    if row.result == "manual" and target is not None and row.merchant_id == target:
        return row
    if row.result != "unmatched":
        raise ConflictError(_RESOLVED, code="usdt_incoming_resolved")
    if target is None or await db.get(Merchant, target) is None:
        raise NotFoundError("merchant not found", code="merchant_not_found")
    amount = row.amount_usdt.quantize(CENT, rounding=ROUND_DOWN)
    await credit_deposit(
        db,
        merchant_id=target,
        amount=amount,
        actor=f"admin:{admin_id}",
        idempotency_key=f"usdt:incoming:{row.id}",
        order_id=None,
        note=f"USDT · {row.tx_id[:10]}… {note or ''}".strip(),
    )
    row.result, row.merchant_id = "manual", target
    row.resolved_by, row.resolved_at, row.note = admin_id, now(), note
    await db.flush()
    log.info("usdt.manual_credit", admin_id=admin_id, amount=str(amount), tx_id=row.tx_id)
    return row


async def dismiss(db: AsyncSession, *, incoming_id: str, note: str, admin_id: str) -> UsdtIncoming:
    """Close an unmatched transfer without crediting (refunded, not a top-up).

    Raises:
        NotFoundError: The transfer does not exist.
        ConflictError: ``usdt_incoming_resolved`` when it was credited.
    """
    row = await _locked(db, incoming_id)
    if row.result == "dismissed":
        return row
    if row.result != "unmatched":
        raise ConflictError(_RESOLVED, code="usdt_incoming_resolved")
    row.result, row.note = "dismissed", note
    row.resolved_by, row.resolved_at = admin_id, now()
    await db.flush()
    log.info("usdt.dismissed", admin_id=admin_id, tx_id=row.tx_id)
    return row


__all__ = ["change_address", "credit", "dismiss", "reenable"]
