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
from yupay.modules.integrations.models import (
    NOVA_STEAM_SENTINEL,
    SkuSupplierMapping,
    SupplierCatalogCache,
)

if TYPE_CHECKING:
    from yupay.modules.integrations.schemas import DenomImportIn, GameImportIn
    from yupay.modules.sourcing.service import Decision

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
    return (
        payload.supplier_slug == "nova"
        and payload.external_product_id.strip() == NOVA_STEAM_SENTINEL
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

    ``updated`` reflects whether ``Sku.cost_usdt`` actually changed value.
    ``wrote_cost`` is the broader fact: whether this call was even *allowed*
    to touch ``Sku.cost_usdt`` — true only when ``mapping`` is the supplier
    the SKU is actually routed to (the routed-supplier rule in
    :func:`refresh_sku_cost_for_mapping`). So four combinations are all
    real: routed with a price move (``wrote_cost=True, updated=True``),
    routed with no move (``wrote_cost=True, updated=False``), not routed
    (``wrote_cost=False, updated=False`` — a history row may still have been
    written, ``Sku.cost_usdt`` never was), and no price at all
    (``wrote_cost=False, updated=False, reason=...``).

    ``reason`` is populated whenever the call produced no price to act on
    (network failure, catalogue/offer miss, not configured, the NOVA Steam
    sentinel, ...) to give the admin UI / scheduler logs something to
    surface. ``old_price``/``new_price``/``margin_percent`` are populated
    only when ``wrote_cost`` is true *and* the SKU had a saved margin, so
    ``price_usd`` was re-derived alongside the cost — see
    ``catalog.admin_service.set_sku_cost_usdt``.
    """

    updated: bool
    wrote_cost: bool = False
    old_cost: Any | None = None
    new_cost: Any | None = None
    source: str | None = None
    reason: str | None = None
    old_price: Any | None = None
    new_price: Any | None = None
    margin_percent: Any | None = None


@dataclass(frozen=True)
class _RawPrice:
    """One supplier's answer to "what does this mapping cost right now".

    Exactly one of ``amount``/``reason`` matters to the caller: ``reason``
    set means the lookup produced no usable number (network failure,
    catalogue/offer miss, not configured, the NOVA Steam sentinel) and
    nothing else here should be trusted; otherwise ``amount`` is the raw
    upstream value and ``source`` names where it came from.
    """

    amount: object | None
    source: str
    reason: str | None = None


async def _g2b_raw_price(  # noqa: PLR0911 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession, mapping: SkuSupplierMapping
) -> _RawPrice:
    """G2B's price for one mapping.

    Voucher mappings read the catalog cache (populated by the periodic
    sync); game mappings call ``games_catalogue`` live and match on the
    denom name. Carved out of :func:`refresh_sku_cost_for_mapping` verbatim
    so NOVA could get a sibling without turning that function into one long
    per-supplier branch — the behaviour is unchanged from before the
    dispatch existed.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return _RawPrice(amount=None, source="", reason="G2B is not configured")

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
                return _RawPrice(
                    amount=None,
                    source="",
                    reason="ваучер не найден в кэше — синхронизируйте каталог",
                )
            return _RawPrice(
                amount=cache_row.raw.get("unit_price"),
                source="supplier_catalog_cache.unit_price",
            )
        # game
        denom_name = (mapping.external_variant_id or "").strip()
        if not denom_name:
            return _RawPrice(amount=None, source="", reason="у маппинга не указан catalogue_name")
        client = fulfiller._client()
        rows = await client.games_catalogue(mapping.external_product_id)
        match = next(
            (r for r in rows if str(r.get("name") or "").strip() == denom_name),
            None,
        )
        if match is None:
            return _RawPrice(
                amount=None,
                source="",
                reason=f"denom «{denom_name}» не найден в каталоге G2B",
            )
        return _RawPrice(amount=match.get("amount"), source="g2b.games_catalogue.amount")
    except Exception as exc:  # noqa: BLE001 -- best effort
        return _RawPrice(amount=None, source="", reason=f"ошибка обращения к G2B: {exc!s}"[:200])


async def _nova_raw_price(
    mapping: SkuSupplierMapping,
    *,
    offers_cache: dict[str, dict[str, Any]] | None,
) -> _RawPrice:
    """NOVA's price for one mapping: ``GET /topups/offers`` for the
    mapping's category (``external_product_id``), matched on the offer id
    (``external_variant_id``), reading ``price_usd`` off the match.

    Steam (:data:`NOVA_STEAM_SENTINEL`) has no catalogue price to look up —
    its cost is a share of the face value the customer picks at checkout,
    not a catalogue number (ADR-0082 §4) — so it is reported as a reason
    before any network call, and the caller must write nothing for it, not
    even history.

    ``offers_cache``, when given, is checked for the mapping's
    ``external_product_id`` before calling NOVA at all — a caller
    refreshing many SKUs of the same category (a whole brand) fetches the
    category once and passes the same map to every one of them. Building
    that cache is the caller's job (the scheduler); this function only
    reads it.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    category_id = mapping.external_product_id.strip()
    if category_id == NOVA_STEAM_SENTINEL:
        return _RawPrice(
            amount=None,
            source="",
            reason=(
                "у Steam-пополнения NOVA нет каталожной цены — стоимость зависит "
                "от суммы, которую выбирает покупатель"
            ),
        )
    offer_id = (mapping.external_variant_id or "").strip()
    if not offer_id:
        return _RawPrice(amount=None, source="", reason="у маппинга не указан offer_id")

    fulfiller = REGISTRY.get("nova")
    if not isinstance(fulfiller, NovaFulfiller) or not fulfiller.available:
        return _RawPrice(amount=None, source="", reason="NOVA is not configured")

    try:
        body = (
            offers_cache[category_id]
            if offers_cache is not None and category_id in offers_cache
            else await fulfiller._client().get_offers(category_id)
        )
        offers = [o for o in (body.get("offers") or []) if isinstance(o, dict)]
        match = next(
            (o for o in offers if str(o.get("offer_id") or "").strip() == offer_id),
            None,
        )
        if match is None:
            return _RawPrice(
                amount=None,
                source="",
                reason=f"offer «{offer_id}» не найден в каталоге NOVA",
            )
        return _RawPrice(amount=match.get("price_usd"), source="nova.get_offers.price_usd")
    except Exception as exc:  # noqa: BLE001 -- best effort, mirrors G2B
        return _RawPrice(amount=None, source="", reason=f"ошибка обращения к NOVA: {exc!s}"[:200])


def _is_routed_supplier(decision: Decision, supplier_slug: str) -> bool:
    """Whether ``supplier_slug`` is the supplier this SKU actually buys from.

    Matches the two shapes ``sourcing.resolve_for_sku`` answers in:

    - A ``top_up`` SKU, or any SKU carrying an explicit ``force_supplier``
      rule, names the supplier directly: ``decision.primary ==
      "supplier:<slug>"``.
    - A ``voucher`` SKU with no override routes to inventory first by
      kind-default (``decision.primary == "inventory"``); the supplier that
      would actually be charged on a stockout is named in
      ``decision.fallback`` instead, and *that* one owns the cost basis —
      the pre-existing on-save refresh for voucher mappings already relied
      on this being true (one active mapping, always refreshed) before this
      function knew about routing at all, and a second voucher mapping must
      not stop it from being true.

    A ``force_inventory`` rule (``fallback=None``, strict) or the
    ``manual`` route matches no supplier, on purpose: no live supplier
    price is "the" cost basis there either.
    """
    target = f"supplier:{supplier_slug}"
    if decision.primary == target:
        return True
    return decision.primary == "inventory" and decision.fallback == target


async def _last_history_cost(db: AsyncSession, *, sku_id: str, supplier_slug: str) -> Any | None:
    """Most recent ``supplier_price_history.cost_usdt`` for one
    SKU↔supplier pair, or ``None`` if that pair has never been recorded.

    Typed ``Any`` because ``SupplierPriceHistory.cost_usdt`` is itself
    ``Mapped[Any]`` (a ``Numeric`` column) — same reason
    :class:`CostRefreshOutcome`'s cost fields are ``Any | None``.

    The "previous" baseline for a **non-routed** mapping: judged against
    its own last recorded price, never against ``Sku.cost_usdt`` — which
    belongs to whichever supplier is actually routed, a different number
    entirely once two mappings are active on the same SKU.
    """
    from yupay.modules.integrations.models import SupplierPriceHistory

    return (
        await db.execute(
            select(SupplierPriceHistory.cost_usdt)
            .where(
                SupplierPriceHistory.sku_id == sku_id,
                SupplierPriceHistory.supplier_slug == supplier_slug,
            )
            .order_by(SupplierPriceHistory.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def refresh_sku_cost_for_mapping(  # noqa: PLR0911 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession,
    *,
    mapping: SkuSupplierMapping,
    record_history: bool = True,
    nova_offers_cache: dict[str, dict[str, Any]] | None = None,
) -> CostRefreshOutcome:
    """Pull the upstream price for ``mapping`` and persist it.

    Handles ``g2b`` (:func:`_g2b_raw_price`) and ``nova``
    (:func:`_nova_raw_price`); any other supplier is reported through the
    outcome, not raised. Every active mapping that produces a usable price
    gets a ``supplier_price_history`` row — that table is the per-supplier
    comparison the admin screen reads, and it is written whoever the
    supplier is.

    ``Sku.cost_usdt`` is different. It is not a fact about a supplier — it
    is **our** cost basis: retail price derives from it
    (``catalog.admin_service.set_sku_cost_usdt`` re-derives ``price_usd``
    from ``margin_percent`` whenever the cost moves), an order line freezes
    it at checkout, and the margin report subtracts it from revenue. If two
    suppliers were both allowed to write it, a SKU's retail price would
    flip between their two numbers every hour, depending on which mapping
    the refresh happened to reach last — not hypothetical: 22 production
    SKUs already carry two active mappings (G2B and NOVA) on this branch.
    So exactly one supplier may write it: the one
    ``sourcing.resolve_for_sku`` says this SKU actually routes to (see
    :func:`_is_routed_supplier`). Every other active mapping records
    history and touches nothing else.

    Centralised here (instead of inside the upsert route) so the
    hourly scheduler can reuse the exact same logic without dragging
    HTTP-layer types into a background actor.

    Args:
        db: Active session (caller commits).
        mapping: The mapping to refresh.
        record_history: Whether to persist a ``supplier_price_history`` row
            when the price actually moved since that supplier's own last
            recorded price. ``True`` in every current caller; a hook for a
            future dry-run.
        nova_offers_cache: Pre-fetched ``{category_id: get_offers() body}``
            for NOVA mappings, so a caller refreshing many SKUs of the same
            category (e.g. a whole brand) fetches it once instead of once
            per SKU. Ignored for ``g2b`` mappings. Building the cache is
            the caller's job — this function only reads it.

    Returns:
        A :class:`CostRefreshOutcome`. Never raises — every failure mode is
        reported through it. The caller is responsible for committing the
        session.
    """
    from decimal import Decimal, InvalidOperation

    from yupay.core.ids import new_id
    from yupay.modules.catalog import admin_service as catalog_svc
    from yupay.modules.integrations.models import SupplierPriceHistory
    from yupay.modules.sourcing import api as sourcing_api

    if mapping.supplier_slug == "g2b":
        lookup = await _g2b_raw_price(db, mapping)
    elif mapping.supplier_slug == "nova":
        lookup = await _nova_raw_price(mapping, offers_cache=nova_offers_cache)
    else:
        return CostRefreshOutcome(
            updated=False,
            reason=f"cost sync not supported for supplier '{mapping.supplier_slug}'",
        )

    if lookup.reason is not None:
        return CostRefreshOutcome(updated=False, reason=lookup.reason, source=lookup.source or None)

    raw_amount = lookup.amount
    source = lookup.source
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

    decision = await sourcing_api.resolve_for_sku(db, mapping.sku_id)
    routed = _is_routed_supplier(decision, mapping.supplier_slug)

    if not routed:
        previous = await _last_history_cost(
            db, sku_id=mapping.sku_id, supplier_slug=mapping.supplier_slug
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
            updated=False,
            wrote_cost=False,
            old_cost=previous,
            new_cost=new_cost,
            source=source,
        )

    try:
        cost_update = await catalog_svc.set_sku_cost_usdt(
            db, sku_id=mapping.sku_id, new_cost=new_cost
        )
    except Exception as exc:  # noqa: BLE001
        return CostRefreshOutcome(
            updated=False, reason=f"не удалось записать cost_usdt: {exc!s}"[:200]
        )

    previous = cost_update.previous_cost
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
        wrote_cost=True,
        old_cost=previous,
        new_cost=new_cost,
        source=source,
        old_price=cost_update.previous_price,
        new_price=cost_update.new_price,
        margin_percent=cost_update.margin_percent,
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
    "list_active_mappings",
    "list_catalog",
    "list_mappings",
    "list_price_history",
    "mapped_external_product_ids",
    "refresh_sku_cost_for_mapping",
    "sku_codes_for",
    "upsert_catalog_entry",
    "upsert_mapping",
]
