"""Integrations service: CRUD over ``sku_supplier_mapping`` and the catalog cache.

The mapping table is the source of truth for *what* a supplier should sell when
the YuPay fulfilment saga routes a SKU through them. The catalog cache is
populated by a periodic sync from the supplier's own API and is consumed only
by the admin autocomplete UI — never by the live fulfilment path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache

MappingKind = Literal["voucher", "game"]
CatalogKind = Literal["voucher", "game", "game_denom"]


@dataclass(frozen=True)
class MappingUpsert:
    """Payload for upserting a mapping."""

    sku_id: str
    supplier_slug: str
    kind: MappingKind
    external_product_id: str
    external_variant_id: str | None
    quantity: int
    extra: dict[str, Any]
    is_active: bool
    updated_by: str | None


async def get_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str,
) -> SkuSupplierMapping | None:
    """Return the mapping for ``(sku_id, supplier_slug)`` or ``None``.

    Fulfillment adapters call this on every ``fulfill()`` to translate our
    SKU into the supplier's product identifier. They are responsible for
    treating ``None`` and ``is_active=False`` as "no mapping" — this
    function does not filter by ``is_active`` so the admin UI can still
    list disabled rows.
    """
    return (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.supplier_slug == supplier_slug,
            )
        )
    ).scalar_one_or_none()


async def list_mappings(
    db: AsyncSession,
    *,
    supplier_slug: str | None = None,
    sku_id: str | None = None,
    limit: int = 200,
) -> list[SkuSupplierMapping]:
    """List mappings, newest first."""
    stmt = select(SkuSupplierMapping).order_by(SkuSupplierMapping.updated_at.desc())
    if supplier_slug is not None:
        stmt = stmt.where(SkuSupplierMapping.supplier_slug == supplier_slug)
    if sku_id is not None:
        stmt = stmt.where(SkuSupplierMapping.sku_id == sku_id)
    stmt = stmt.limit(min(limit, 500))
    return list((await db.execute(stmt)).scalars().all())


async def upsert_mapping(db: AsyncSession, payload: MappingUpsert) -> SkuSupplierMapping:
    """Create or overwrite the mapping row for ``(sku_id, supplier_slug)``."""
    if not payload.external_product_id.strip():
        raise ValidationError("external_product_id is required")
    if payload.quantity <= 0:
        raise ValidationError("quantity must be positive")
    if payload.kind == "game" and not payload.external_variant_id:
        # Game orders need a catalogue_name / denom id — voucher orders don't.
        raise ValidationError(
            "external_variant_id is required for kind='game'",
        )

    existing = await get_mapping(db, sku_id=payload.sku_id, supplier_slug=payload.supplier_slug)
    if existing is None:
        row = SkuSupplierMapping(
            sku_id=payload.sku_id,
            supplier_slug=payload.supplier_slug,
            kind=payload.kind,
            external_product_id=payload.external_product_id.strip(),
            external_variant_id=(
                payload.external_variant_id.strip() if payload.external_variant_id else None
            ),
            quantity=payload.quantity,
            extra=payload.extra,
            is_active=payload.is_active,
            updated_by=payload.updated_by,
        )
        db.add(row)
    else:
        existing.kind = payload.kind
        existing.external_product_id = payload.external_product_id.strip()
        existing.external_variant_id = (
            payload.external_variant_id.strip() if payload.external_variant_id else None
        )
        existing.quantity = payload.quantity
        existing.extra = payload.extra
        existing.is_active = payload.is_active
        existing.updated_by = payload.updated_by
        existing.updated_at = now()
        row = existing
    await db.flush()
    return row


async def delete_mapping(db: AsyncSession, *, sku_id: str, supplier_slug: str) -> None:
    """Drop a mapping row. 404 if it doesn't exist."""
    row = await get_mapping(db, sku_id=sku_id, supplier_slug=supplier_slug)
    if row is None:
        raise NotFoundError("supplier mapping not found")
    await db.delete(row)
    await db.flush()


async def upsert_catalog_entry(
    db: AsyncSession,
    *,
    supplier_slug: str,
    kind: CatalogKind,
    external_id: str,
    title: str,
    raw: dict[str, Any],
) -> None:
    """Persist a single catalog cache row, replacing any existing entry.

    ON CONFLICT DO UPDATE keeps the table small and the latest snapshot
    authoritative — we don't keep historical versions because the supplier
    catalog drifts continuously.
    """
    stmt = pg_insert(SupplierCatalogCache).values(
        supplier_slug=supplier_slug,
        kind=kind,
        external_id=external_id,
        title=title,
        raw=raw,
        fetched_at=now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["supplier_slug", "kind", "external_id"],
        set_={
            "title": stmt.excluded.title,
            "raw": stmt.excluded.raw,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await db.execute(stmt)


async def list_catalog(
    db: AsyncSession,
    *,
    supplier_slug: str,
    kind: CatalogKind | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[SupplierCatalogCache]:
    """List cached catalog rows for autocomplete."""
    stmt = (
        select(SupplierCatalogCache)
        .where(SupplierCatalogCache.supplier_slug == supplier_slug)
        .order_by(SupplierCatalogCache.title)
        .limit(min(limit, 500))
    )
    if kind is not None:
        stmt = stmt.where(SupplierCatalogCache.kind == kind)
    if search:
        needle = f"%{search.strip().lower()}%"
        from sqlalchemy import func

        stmt = stmt.where(func.lower(SupplierCatalogCache.title).like(needle))
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "CatalogKind",
    "MappingKind",
    "MappingUpsert",
    "delete_mapping",
    "get_mapping",
    "list_catalog",
    "list_mappings",
    "upsert_catalog_entry",
    "upsert_mapping",
]
