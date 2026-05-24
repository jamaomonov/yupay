"""Inventory service: bulk-upload, atomic reservation, counts.

The cleartext code only ever exists in memory inside this module for the
duration of one call. Logs and persisted attempt payloads never include it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.inventory.crypto import code_hash, decrypt, encrypt
from yupay.modules.inventory.models import InventoryCode, InventoryUpload

log = get_logger("yupay.inventory.service")

MAX_BULK = 5000


class NoStockError(Exception):
    """Raised when ``reserve_and_issue`` finds nothing available."""


@dataclass(frozen=True)
class BulkUploadResult:
    upload_id: str
    total: int
    succeeded: int
    duplicates: int


@dataclass(frozen=True)
class IssuedCode:
    """What ``reserve_and_issue`` returns. Code is cleartext — handle with care."""

    code: str
    inventory_code_id: str
    expires_at: object | None


@dataclass(frozen=True)
class SkuCounts:
    available: int
    reserved: int
    issued: int
    voided: int


def _normalize_code(raw: str) -> str:
    return raw.strip()


async def bulk_upload(
    db: AsyncSession,
    *,
    sku_id: str,
    codes: list[str],
    uploaded_by: str,
) -> BulkUploadResult:
    """Insert many codes for one SKU. Duplicates (per ``sku_id, code_hash``) are
    silently skipped — the upload record reports the count."""
    if not codes:
        raise ValidationError("codes is empty")
    if len(codes) > MAX_BULK:
        raise ValidationError(
            f"bulk upload is capped at {MAX_BULK} codes per call",
            extra={"got": len(codes), "max": MAX_BULK},
        )

    upload_id = new_id()
    succeeded = 0
    duplicates = 0
    seen_hashes_in_batch: set[str] = set()

    for raw in codes:
        plaintext = _normalize_code(raw)
        if not plaintext:
            duplicates += 1
            continue
        h = code_hash(plaintext)
        if h in seen_hashes_in_batch:
            duplicates += 1
            continue
        seen_hashes_in_batch.add(h)
        ciphertext, nonce = encrypt(plaintext)
        row = InventoryCode(
            id=new_id(),
            sku_id=sku_id,
            code_ciphertext=ciphertext,
            code_nonce=nonce,
            code_hash=h,
            state="available",
            uploaded_by=uploaded_by,
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Re-fetch the existing row's id is unnecessary; we just count it.
            duplicates += 1
            continue
        succeeded += 1

    upload = InventoryUpload(
        id=upload_id,
        sku_id=sku_id,
        total=len(codes),
        succeeded=succeeded,
        duplicates=duplicates,
        uploaded_by=uploaded_by,
    )
    db.add(upload)
    await db.flush()
    log.info(
        "inventory.bulk_upload",
        sku_id=sku_id,
        total=len(codes),
        succeeded=succeeded,
        duplicates=duplicates,
    )
    return BulkUploadResult(
        upload_id=upload_id,
        total=len(codes),
        succeeded=succeeded,
        duplicates=duplicates,
    )


async def reserve_and_issue(
    db: AsyncSession,
    *,
    sku_id: str,
    order_item_id: str,
) -> IssuedCode:
    """Atomically reserve one available code for an order item.

    Idempotent: if a code is already in ``reserved``/``issued`` state for this
    ``order_item_id``, returns the same row instead of consuming another.
    """
    existing = (
        await db.execute(
            select(InventoryCode)
            .where(InventoryCode.order_item_id == order_item_id)
            .where(InventoryCode.state.in_(("reserved", "issued")))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return IssuedCode(
            code=decrypt(existing.code_ciphertext, existing.code_nonce),
            inventory_code_id=existing.id,
            expires_at=existing.expires_at,
        )

    # Race-safe pull of one available row. SKIP LOCKED lets parallel workers
    # claim different rows without blocking each other.
    pick_stmt = (
        select(InventoryCode.id)
        .where(
            InventoryCode.sku_id == sku_id,
            InventoryCode.state == "available",
        )
        .order_by(InventoryCode.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    picked_id = (await db.execute(pick_stmt)).scalar_one_or_none()
    if picked_id is None:
        raise NoStockError(f"no available codes for SKU {sku_id}")

    moment = now()
    await db.execute(
        update(InventoryCode)
        .where(InventoryCode.id == picked_id)
        .values(
            state="issued",
            order_item_id=order_item_id,
            reserved_at=moment,
            issued_at=moment,
        )
    )
    await db.flush()
    row = (
        await db.execute(select(InventoryCode).where(InventoryCode.id == picked_id))
    ).scalar_one()
    return IssuedCode(
        code=decrypt(row.code_ciphertext, row.code_nonce),
        inventory_code_id=row.id,
        expires_at=row.expires_at,
    )


async def void_for_order_item(db: AsyncSession, *, order_item_id: str, reason: str) -> int:
    """Free up codes attached to an order item (e.g. on cancel). Returns the count."""
    result = await db.execute(
        update(InventoryCode)
        .where(
            InventoryCode.order_item_id == order_item_id,
            InventoryCode.state.in_(("reserved", "issued")),
        )
        .values(state="voided", voided_at=now())
    )
    count = result.rowcount or 0  # type: ignore[attr-defined]
    if count:
        log.info("inventory.void", order_item_id=order_item_id, count=count, reason=reason)
    return count


async def counts_for_sku(db: AsyncSession, sku_id: str) -> SkuCounts:
    stmt = (
        select(InventoryCode.state, func.count(InventoryCode.id))
        .where(InventoryCode.sku_id == sku_id)
        .group_by(InventoryCode.state)
    )
    rows = (await db.execute(stmt)).all()
    counts = {state: int(c) for state, c in rows}
    return SkuCounts(
        available=counts.get("available", 0),
        reserved=counts.get("reserved", 0),
        issued=counts.get("issued", 0),
        voided=counts.get("voided", 0),
    )


async def list_codes_admin(
    db: AsyncSession,
    *,
    sku_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[tuple[InventoryCode, str]]:
    """Admin-only listing. Decrypts each row's code."""
    stmt = select(InventoryCode).order_by(InventoryCode.created_at.desc()).limit(min(limit, 200))
    if sku_id is not None:
        stmt = stmt.where(InventoryCode.sku_id == sku_id)
    if state is not None:
        stmt = stmt.where(InventoryCode.state == state)
    rows = list((await db.execute(stmt)).scalars().all())
    return [(r, decrypt(r.code_ciphertext, r.code_nonce)) for r in rows]


async def get_code_for_order_item(db: AsyncSession, order_item_id: str) -> str | None:
    """Cleartext code for an order item, if it was fulfilled from stock."""
    row = (
        await db.execute(
            select(InventoryCode)
            .where(InventoryCode.order_item_id == order_item_id)
            .where(InventoryCode.state == "issued")
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return decrypt(row.code_ciphertext, row.code_nonce)


async def get_sku_or_404(db: AsyncSession, sku_id: str) -> None:
    """Tiny guard used by routes; raises NotFound if SKU is missing."""
    from yupay.modules.catalog.models import Sku

    exists = (await db.execute(select(Sku.id).where(Sku.id == sku_id))).scalar_one_or_none()
    if exists is None:
        raise NotFoundError("sku not found")


__all__ = [
    "MAX_BULK",
    "BulkUploadResult",
    "ConflictError",
    "IssuedCode",
    "NoStockError",
    "SkuCounts",
    "bulk_upload",
    "counts_for_sku",
    "get_code_for_order_item",
    "get_sku_or_404",
    "list_codes_admin",
    "reserve_and_issue",
    "void_for_order_item",
]
