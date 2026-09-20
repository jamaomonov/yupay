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

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.catalog.image_url_safety import validate_optional_public_image_url
from yupay.modules.integrations.models import (
    NOVA_FRAGMENT_STARS,
    NOVA_STEAM_SENTINEL,
    SkuSupplierMapping,
    SupplierCatalogCache,
)

if TYPE_CHECKING:
    from yupay.modules.integrations.schemas import DenomImportIn, GameImportIn

MappingKind = Literal["voucher", "game", "gift"]
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


#: Suppliers whose game catalogue includes **amount-priced** services — ones
#: with no denominations at all, where what to buy is a quantity rather than a
#: catalogue entry (G-Engine calls them ``unfixed``; Telegram Stars is one).
#:
#: The rule below was written when G2B was the only supplier and every game
#: top-up named a denomination. Applied to an unfixed service it demands an id
#: that does not exist upstream, which would make such a SKU unmappable — from
#: this seed *and* from the admin form, which calls the same function.
_AMOUNT_PRICED_SUPPLIERS = frozenset({"gengine"})


def _is_amount_priced(payload: MappingUpsert) -> bool:
    """Whether this mapping buys an amount rather than a catalogue entry.

    Two shapes qualify, and they qualify for the same reason: upstream has no
    denomination id to name, so demanding one would make the SKU unmappable
    from the admin form and from every seed.

    - a supplier whose whole game catalogue is amount-priced
      (:data:`_AMOUNT_PRICED_SUPPLIERS` — G-Engine's ``unfixed`` services);
    - NOVA's **Steam** mapping specifically
      (:data:`NOVA_STEAM_SENTINEL`), which is one row rather than a supplier:
      their Steam endpoint takes a login and an amount, while their games
      endpoint still needs an ``offer_id`` and is still checked for one.

    That second case is narrow on purpose. Adding ``nova`` to the set outright
    would also let an operator save a NOVA *game* mapping with no offer, and
    the first order on it would fail at our own guard instead of at the form —
    feedback moved from the moment of the mistake to the moment it costs a
    customer their order.
    """
    if payload.supplier_slug in _AMOUNT_PRICED_SUPPLIERS:
        return True
    # ``fragment-premium`` is deliberately absent: its months *are* the
    # variant, so a Premium mapping saved without one is a mistake the admin
    # form should still catch.
    return payload.supplier_slug == "nova" and payload.external_product_id.strip() in (
        NOVA_STEAM_SENTINEL,
        NOVA_FRAGMENT_STARS,
    )


async def upsert_mapping(db: AsyncSession, payload: MappingUpsert) -> SkuSupplierMapping:
    """Create or overwrite the mapping row for ``(sku_id, supplier_slug)``."""
    if not payload.external_product_id.strip():
        raise ValidationError("external_product_id is required")
    if payload.quantity <= 0:
        raise ValidationError("quantity must be positive")
    if (
        payload.kind == "game"
        and not payload.external_variant_id
        and not _is_amount_priced(payload)
    ):
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


async def prune_catalog_denoms(
    db: AsyncSession,
    *,
    supplier_slug: str,
    parent_external_id: str,
    keep: set[str],
) -> int:
    """Forget cached denominations of one game the supplier stopped listing.

    ``upsert_catalog_entry`` only ever writes, so before this existed the
    cache never forgot: a pack withdrawn upstream stayed in the mapping
    picker forever, and anything diffing the cache against a fresh pass —
    ``catalog_watch.watch_cached_variants`` does exactly that — could never
    see a position disappear. That is the bug this closes.

    ``keep`` is what the pass just saw. An empty ``keep`` prunes nothing:
    a fetch that returned no rows is an outage or an API change, never
    "the supplier delisted the whole game at once" — the same rule the
    catalogue watch applies to an empty catalogue.

    Returns the number of rows removed.
    """
    if not keep:
        return 0
    result = await db.execute(
        sa_delete(SupplierCatalogCache).where(
            SupplierCatalogCache.supplier_slug == supplier_slug,
            SupplierCatalogCache.kind == "game_denom",
            SupplierCatalogCache.parent_external_id == parent_external_id,
            SupplierCatalogCache.external_id.notin_(tuple(keep)),
        )
    )
    # `Result` is the declared return type of `execute`; only the
    # `CursorResult` a DML statement actually yields carries `rowcount`.
    return int(getattr(result, "rowcount", 0) or 0)


async def upsert_catalog_entry(
    db: AsyncSession,
    *,
    supplier_slug: str,
    kind: CatalogKind,
    external_id: str,
    title: str,
    raw: dict[str, Any],
    parent_external_id: str | None = None,
    price_usdt: Decimal | None = None,
) -> None:
    """Persist a single catalog cache row, replacing any existing entry.

    ON CONFLICT DO UPDATE keeps the table small and the latest snapshot
    authoritative — we don't keep historical versions because the supplier
    catalog drifts continuously.

    ``parent_external_id``/``price_usdt`` matter only for a ``game_denom``
    row (the game it belongs to, and the supplier's own price for it, when
    reported) — every other kind leaves them ``None``, and ``None`` is stored
    as ``''`` because the column is part of the key (see the model, and 0084
    for why it had to be).
    """
    stmt = pg_insert(SupplierCatalogCache).values(
        supplier_slug=supplier_slug,
        kind=kind,
        external_id=external_id,
        title=title,
        parent_external_id=parent_external_id or "",
        price_usdt=price_usdt,
        raw=raw,
        fetched_at=now(),
    )
    stmt = stmt.on_conflict_do_update(
        # Must match the primary key exactly. While ``parent_external_id`` was
        # missing here, a denomination id shared by two games conflicted on
        # the first game's row and overwrote its parent with the second's.
        index_elements=["supplier_slug", "kind", "external_id", "parent_external_id"],
        set_={
            "title": stmt.excluded.title,
            "price_usdt": stmt.excluded.price_usdt,
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
    parent_external_id: str | None = None,
    limit: int = 100,
) -> list[SupplierCatalogCache]:
    """List cached catalog rows for autocomplete.

    ``parent_external_id``, when given, narrows a ``game_denom`` listing down
    to one game's denominations — the admin picker's second step once an
    operator has chosen the game in the first.
    """
    stmt = (
        select(SupplierCatalogCache)
        .where(SupplierCatalogCache.supplier_slug == supplier_slug)
        .order_by(SupplierCatalogCache.title)
        .limit(min(limit, 500))
    )
    if kind is not None:
        stmt = stmt.where(SupplierCatalogCache.kind == kind)
    if parent_external_id is not None:
        stmt = stmt.where(SupplierCatalogCache.parent_external_id == parent_external_id)
    if search:
        needle = f"%{search.strip().lower()}%"
        from sqlalchemy import func

        stmt = stmt.where(func.lower(SupplierCatalogCache.title).like(needle))
    return list((await db.execute(stmt)).scalars().all())


async def list_price_history(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str | None = None,
    limit: int = 100,
) -> list[Any]:
    """Last ``limit`` price points for a SKU, newest first.

    ``supplier_slug``, when given, narrows the rows to one supplier's own
    series. Before this branch ``supplier_price_history`` held only G2B
    rows, so every existing caller reads the unfiltered (default) series and
    keeps working unchanged; Task 1 of this branch made the table
    multi-supplier — every active mapping now writes a row on refresh — and
    22 production SKUs already carry interleaved G2B/NOVA history, which an
    unfiltered read cannot tell apart.
    """
    from yupay.modules.integrations.models import SupplierPriceHistory

    stmt = (
        select(SupplierPriceHistory)
        .where(SupplierPriceHistory.sku_id == sku_id)
        .order_by(SupplierPriceHistory.captured_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    if supplier_slug is not None:
        stmt = stmt.where(SupplierPriceHistory.supplier_slug == supplier_slug)
    return list((await db.execute(stmt)).scalars().all())


# Moved to `cost_refresh.py` when this file passed 900 lines; re-exported so
# every existing caller (`price_refresh`, the admin save route) keeps importing
# it from here. See that module for the rule it holds.
from yupay.modules.integrations.cost_refresh import (  # noqa: E402
    CostRefreshOutcome,
    is_routed_supplier,
    refresh_sku_cost_for_mapping,
    supports_price_collection,
)


async def mapped_external_product_ids(
    db: AsyncSession,
    *,
    supplier_slug: str,
    kind: CatalogKind,
) -> list[str]:
    """Distinct upstream product ids that active mappings point at.

    The catalogue sync refreshes these by id rather than paging the supplier's
    whole list: we only ever price what we map, and the list is two orders of
    magnitude larger than the mapped set.
    """
    stmt = (
        select(SkuSupplierMapping.external_product_id)
        .where(
            SkuSupplierMapping.supplier_slug == supplier_slug,
            SkuSupplierMapping.kind == kind,
            SkuSupplierMapping.is_active.is_(True),
        )
        .distinct()
        .order_by(SkuSupplierMapping.external_product_id)
    )
    return [row for row in (await db.execute(stmt)).scalars().all() if row]


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
    "is_routed_supplier",
    "list_active_mappings",
    "list_catalog",
    "list_mappings",
    "list_price_history",
    "mapped_external_product_ids",
    "refresh_sku_cost_for_mapping",
    "sku_codes_for",
    "supports_price_collection",
    "upsert_catalog_entry",
    "upsert_mapping",
]
