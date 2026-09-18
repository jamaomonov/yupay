"""Per-supplier raw price lookups for the cost-refresh pipeline.

Split out of ``cost_refresh.py`` when that module passed 495 lines (§6
AGENTS.md: file length soft limit 400 LOC, split before 500) — the same
reasoning ``sourcing/brand_overview.py`` was split out of
``sourcing/service.py`` for on this same branch. The seam here is "ask the
supplier what it costs" (this module) versus "decide who is allowed to
write that number, and persist it" (``cost_refresh.py``, which dispatches
into this module by ``mapping.supplier_slug`` and owns everything
downstream of the raw price). Adding a third supplier's lookup is a third
function here; it never touches ``cost_refresh.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yupay.modules.integrations.models import (
    NOVA_STEAM_SENTINEL,
    SkuSupplierMapping,
    SupplierCatalogCache,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    denom name. Carved out of ``cost_refresh.refresh_sku_cost_for_mapping``
    verbatim so NOVA could get a sibling without turning that function into
    one long per-supplier branch — the behaviour is unchanged from before
    the dispatch existed.
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


async def _nova_raw_price(  # noqa: PLR0911 -- one refusal per thing that can be wrong, each with its own operator-facing reason
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
        matches = [o for o in offers if str(o.get("offer_id") or "").strip() == offer_id]
        if not matches:
            return _RawPrice(
                amount=None,
                source="",
                reason=f"offer «{offer_id}» не найден в каталоге NOVA",
            )
        if len(matches) > 1:
            # Collected rather than `next(...)`, for the reason the mapping seed
            # states in its own words: an id two offers share is an ambiguity to
            # report, not to resolve by taking whichever the supplier listed
            # first. This function now decides a shelf price, so it is exactly
            # the kind of place that rule was written for.
            names = ", ".join(str(o.get("name")) for o in matches)
            return _RawPrice(
                amount=None,
                source="",
                reason=f"offer «{offer_id}» встречается {len(matches)} раза в каталоге"
                f" NOVA ({names}) — цена неоднозначна, поправьте маппинг",
            )
        return _RawPrice(amount=matches[0].get("price_usd"), source="nova.get_offers.price_usd")
    except Exception as exc:  # noqa: BLE001 -- best effort, mirrors G2B
        return _RawPrice(amount=None, source="", reason=f"ошибка обращения к NOVA: {exc!s}"[:200])
