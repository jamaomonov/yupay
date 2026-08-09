"""Integrations service: CRUD over ``sku_supplier_mapping`` and the catalog cache.

The mapping table is the source of truth for *what* a supplier should sell when
the YuPay fulfilment saga routes a SKU through them. The catalog cache is
populated by a periodic sync from the supplier's own API and is consumed only
by the admin autocomplete UI — never by the live fulfilment path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.catalog.image_url_safety import validate_optional_public_image_url
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache

if TYPE_CHECKING:
    from yupay.modules.integrations.schemas import DenomImportIn, GameImportIn

MappingKind = Literal["voucher", "game"]
CatalogKind = Literal["voucher", "game", "game_denom"]

# Locales every catalog entity carries a translation for. Typed so the import
# helper below can feed them straight into ``TranslationIn(locale=...)``.
_LOCALES: tuple[Literal["ru", "en", "uz"], ...] = ("ru", "en", "uz")


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


@dataclass(frozen=True)
class GameImportResult:
    """Outcome of import_game."""

    brand_id: str
    product_id: str
    created_skus: int
    created_mappings: int
    skipped: list[str]


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


async def sku_codes_for(db: AsyncSession, sku_ids: Iterable[str]) -> dict[str, str]:
    """Batch-resolve ``sku_id -> sku_code`` for the given ids — one query, no N+1.

    ``SkuSupplierMapping`` carries only ``sku_id`` (no ORM relationship to
    ``Sku``); admin list views need the human-readable code instead of a raw
    UUID, so routes call this once after fetching mapping rows.
    """
    from yupay.modules.catalog.models import Sku

    ids = list(dict.fromkeys(sku_ids))
    if not ids:
        return {}
    rows = (await db.execute(select(Sku.id, Sku.sku_code).where(Sku.id.in_(ids)))).all()
    return {row.id: row.sku_code for row in rows}


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


def _sanitize_image_url(url: str | None) -> str | None:
    """Blank out a supplier-provided image URL that fails the SSRF host
    check instead of aborting the whole import.

    ``BrandCreate``/``ProductCreate`` (see ``catalog.admin_schemas``) already
    run the same check via
    ``yupay.modules.catalog.image_url_safety.validate_optional_public_image_url``
    on construction and would raise — which is exactly right for an admin
    typing a URL by hand, but too disruptive here: one bad image field from
    the G2B catalog shouldn't sink an otherwise-valid import of a game and
    all its denominations. So the G2B path pre-filters instead of letting
    the schema raise: an invalid host just means "no image", not "abort".
    """
    try:
        return validate_optional_public_image_url(url)
    except ValueError:
        return None


def _sell_price(cost_usdt: Decimal, margin_percent: Decimal) -> Decimal:
    """price = cost * (1 + margin/100), rounded to cents (half-up)."""
    return (cost_usdt * (Decimal(1) + margin_percent / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _import_denomination(
    db: AsyncSession,
    *,
    product_id: str,
    game_code: str,
    denom: DenomImportIn,
    margin_percent: Decimal,
    admin_id: str,
    sort_order: int,
) -> None:
    """Create one SKU + its G2B 'game' mapping. Caller pre-filters skips."""
    from yupay.modules.catalog import admin_schemas as catalog_schemas
    from yupay.modules.catalog import admin_service as catalog

    price = (
        denom.price_usd_override
        if denom.price_usd_override is not None
        else _sell_price(denom.cost_usdt, margin_percent)
    )
    if price <= 0:
        raise ValidationError(f"computed price_usd <= 0 for {denom.sku_code}")
    sku = await catalog.create_sku(
        db,
        catalog_schemas.SkuCreate(
            product_id=product_id,
            sku_code=denom.sku_code,
            denomination=denom.denomination,
            region=denom.region,
            price_usd=price,
            cost_usdt=denom.cost_usdt,
            # Position in the request. Left unset, every SKU of an imported game
            # landed on the column default of 0 and the storefront rendered the
            # denominations in whatever order the database happened to return —
            # which is how a "55 / 3688 / 165" ladder happens. The operator's
            # ordering is the only intent available here, so it is the one used.
            sort_order=sort_order,
        ),
    )
    await upsert_mapping(
        db,
        MappingUpsert(
            sku_id=sku.id,
            supplier_slug="g2b",
            kind="game",
            external_product_id=game_code,
            external_variant_id=denom.catalogue_name,
            quantity=denom.quantity,
            extra={},
            is_active=True,
            updated_by=admin_id,
        ),
    )


async def import_game(
    db: AsyncSession, payload: GameImportIn, *, admin_id: str
) -> GameImportResult:
    """Atomically import a G2B game into the catalog.

    Creates (or reuses) a Brand, creates a Product(kind='top_up'), and for
    each denomination a SKU + a 'game' supplier mapping. Does NOT commit —
    the caller (route) owns the transaction boundary, so a failure anywhere
    rolls the whole import back.

    Args:
        db: Active session (caller commits).
        payload: A ``GameImportIn``.
        admin_id: Id of the admin performing the import (mapping audit field).

    Returns:
        GameImportResult with counts and skipped sku_codes.
    """
    from yupay.modules.catalog import admin_schemas as catalog_schemas
    from yupay.modules.catalog import admin_service as catalog
    from yupay.modules.catalog.models import Sku

    if payload.new_brand is not None:
        nb = payload.new_brand
        brand = await catalog.create_brand(
            db,
            catalog_schemas.BrandCreate(
                slug=nb.slug,
                category_id=nb.category_id,
                logo_url=_sanitize_image_url(nb.logo_url),
                hero_image_url=_sanitize_image_url(nb.hero_image_url),
                accent_color=nb.accent_color,
                translations=[
                    catalog_schemas.TranslationIn(locale=loc, name=nb.name) for loc in _LOCALES
                ],
            ),
        )
        brand_id = brand.id
    else:
        if payload.brand_id is None:
            raise ValidationError("brand_id is required for existing_brand import")
        brand = await catalog.get_brand(db, payload.brand_id)
        brand_id = brand.id

    product = await catalog.create_product(
        db,
        catalog_schemas.ProductCreate(
            slug=payload.product.slug,
            brand_id=brand_id,
            kind="top_up",
            supplier_hint="g2b",
            image_url=_sanitize_image_url(payload.product.image_url),
            required_fields=payload.product.required_fields,
            translations=[
                catalog_schemas.TranslationIn(locale=loc, name=payload.product.name)
                for loc in _LOCALES
            ],
        ),
    )

    codes = [d.sku_code for d in payload.denominations]
    existing = set(
        (await db.execute(select(Sku.sku_code).where(Sku.sku_code.in_(codes)))).scalars().all()
    )

    created_skus = 0
    skipped: list[str] = []
    # Enumerated over the request, not over the created rows: a skipped
    # duplicate still consumes its position, so the ones that are created keep
    # the spacing the operator asked for instead of closing up around the gap.
    for position, d in enumerate(payload.denominations):
        if d.sku_code in existing:
            skipped.append(d.sku_code)
            continue
        await _import_denomination(
            db,
            product_id=product.id,
            game_code=payload.game_code,
            denom=d,
            margin_percent=payload.margin_percent,
            admin_id=admin_id,
            sort_order=position,
        )
        created_skus += 1

    return GameImportResult(
        brand_id=brand_id,
        product_id=product.id,
        created_skus=created_skus,
        created_mappings=created_skus,
        skipped=skipped,
    )


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


async def list_price_history(
    db: AsyncSession,
    *,
    sku_id: str,
    limit: int = 100,
) -> list[Any]:
    """Last ``limit`` price points for a SKU, newest first."""
    from yupay.modules.integrations.models import SupplierPriceHistory

    stmt = (
        select(SupplierPriceHistory)
        .where(SupplierPriceHistory.sku_id == sku_id)
        .order_by(SupplierPriceHistory.captured_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    return list((await db.execute(stmt)).scalars().all())


@dataclass(frozen=True)
class CostRefreshOutcome:
    """Return type for :func:`refresh_sku_cost_for_mapping`.

    ``updated`` reflects whether ``Sku.cost_usdt`` actually changed.
    ``reason`` is populated whenever ``updated`` is false to give the
    admin UI / scheduler logs something to surface.
    """

    updated: bool
    old_cost: Any | None = None
    new_cost: Any | None = None
    source: str | None = None
    reason: str | None = None


async def refresh_sku_cost_for_mapping(  # noqa: PLR0911, PLR0912 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession,
    *,
    mapping: SkuSupplierMapping,
    record_history: bool = True,
) -> CostRefreshOutcome:
    """Pull the upstream price for ``mapping`` and persist it to
    ``Sku.cost_usdt`` (plus optionally a row in
    ``supplier_price_history``).

    Centralised here (instead of inside the upsert route) so the
    hourly scheduler can reuse the exact same logic without dragging
    HTTP-layer types into a background actor.

    Never raises — every failure mode is reported through
    :class:`CostRefreshOutcome`. The caller is responsible for
    committing the session.
    """
    from decimal import Decimal, InvalidOperation

    from yupay.core.ids import new_id
    from yupay.modules.catalog import admin_service as catalog_svc
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller
    from yupay.modules.integrations.models import SupplierPriceHistory

    if mapping.supplier_slug != "g2b":
        return CostRefreshOutcome(updated=False, reason="cost sync supported only for g2b today")
    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return CostRefreshOutcome(updated=False, reason="G2B is not configured")

    raw_amount: object = None
    source = ""
    try:
        if mapping.kind == "voucher":
            cache_row = (
                await db.execute(
                    select(SupplierCatalogCache).where(
                        SupplierCatalogCache.supplier_slug == "g2b",
                        SupplierCatalogCache.kind == "voucher",
                        SupplierCatalogCache.external_id == mapping.external_product_id,
                    )
                )
            ).scalar_one_or_none()
            if cache_row is None:
                return CostRefreshOutcome(
                    updated=False,
                    reason="ваучер не найден в кэше — синхронизируйте каталог",
                )
            raw_amount = cache_row.raw.get("unit_price")
            source = "supplier_catalog_cache.unit_price"
        else:  # game
            denom_name = (mapping.external_variant_id or "").strip()
            if not denom_name:
                return CostRefreshOutcome(
                    updated=False, reason="у маппинга не указан catalogue_name"
                )
            client = fulfiller._client()
            rows = await client.games_catalogue(mapping.external_product_id)
            match = next(
                (r for r in rows if str(r.get("name") or "").strip() == denom_name),
                None,
            )
            if match is None:
                return CostRefreshOutcome(
                    updated=False,
                    reason=f"denom «{denom_name}» не найден в каталоге G2B",
                )
            raw_amount = match.get("amount")
            source = "g2b.games_catalogue.amount"
    except Exception as exc:  # noqa: BLE001 -- best effort
        return CostRefreshOutcome(updated=False, reason=f"ошибка обращения к G2B: {exc!s}"[:200])

    if raw_amount is None:
        return CostRefreshOutcome(updated=False, reason="поставщик не вернул цену", source=source)
    try:
        new_cost = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return CostRefreshOutcome(
            updated=False,
            reason=f"непарсимая цена: {raw_amount!r}",
            source=source,
        )
    if new_cost <= 0:
        return CostRefreshOutcome(
            updated=False, reason="цена ≤ 0", source=source, new_cost=str(new_cost)
        )

    try:
        previous = await catalog_svc.set_sku_cost_usdt(db, sku_id=mapping.sku_id, new_cost=new_cost)
    except Exception as exc:  # noqa: BLE001
        return CostRefreshOutcome(
            updated=False, reason=f"не удалось записать cost_usdt: {exc!s}"[:200]
        )

    moved = previous != new_cost
    if record_history and moved:
        db.add(
            SupplierPriceHistory(
                id=new_id(),
                sku_id=mapping.sku_id,
                supplier_slug=mapping.supplier_slug,
                kind=mapping.kind,
                external_product_id=mapping.external_product_id,
                external_variant_id=mapping.external_variant_id,
                cost_usdt=new_cost,
                previous_cost_usdt=previous,
                source=source,
            )
        )

    return CostRefreshOutcome(
        updated=moved,
        old_cost=previous,
        new_cost=new_cost,
        source=source,
    )


async def list_active_mappings(
    db: AsyncSession,
    *,
    supplier_slug: str | None = None,
) -> list[SkuSupplierMapping]:
    """Every active mapping the scheduler should iterate over."""
    stmt = select(SkuSupplierMapping).where(SkuSupplierMapping.is_active.is_(True))
    if supplier_slug is not None:
        stmt = stmt.where(SkuSupplierMapping.supplier_slug == supplier_slug)
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "CatalogKind",
    "CostRefreshOutcome",
    "GameImportResult",
    "MappingKind",
    "MappingUpsert",
    "delete_mapping",
    "get_mapping",
    "import_game",
    "list_active_mappings",
    "list_catalog",
    "list_mappings",
    "list_price_history",
    "refresh_sku_cost_for_mapping",
    "sku_codes_for",
    "upsert_catalog_entry",
    "upsert_mapping",
]
