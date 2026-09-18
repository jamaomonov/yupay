# `integrations` module

Owns the SKU↔supplier wiring: the `sku_supplier_mapping` table (the source of
truth for _what_ a supplier should sell when the fulfilment saga routes a SKU
through them), a `supplier_catalog_cache` that backs admin autocomplete, supplier
health probes, and supplier-cost refresh. Supplier adapter code itself lives in
`fulfillment/suppliers/*`.

## Responsibilities

- Own `sku_supplier_mapping` and `supplier_catalog_cache`.
- Serve the admin CRUD over mappings and the cached supplier catalog.
- Refresh a supplier's price for a mapping (on upsert and via the hourly
  `refresh-all-prices` job), **dispatched by `mapping.supplier_slug`**
  (`cost_refresh.refresh_sku_cost_for_mapping`, split out into its own module
  when `service.py` passed 900 lines. The per-supplier raw-price lookups it
  dispatches into live in `cost_lookup.py` in turn, split out of
  `cost_refresh.py` when that module itself passed 495 lines — G2B reads the
  catalog cache or calls `games_catalogue` live; NOVA calls
  `GET /topups/offers` per category, cached per refresh run so a 19-SKU
  brand makes one call, not nineteen; a NOVA Steam mapping is skipped, it
  has no catalogue price to look up).
  **Only the supplier a SKU actually routes to may write `Sku.cost_usdt`.**
  Every other active mapping still gets refreshed — it just records a
  `supplier_price_history` row and touches nothing else. `Sku.cost_usdt` is
  our cost basis, not a fact about a supplier: retail price derives from it,
  an order line freezes it at checkout, the margin report subtracts it, so
  two suppliers writing it on the same SKU would flip that SKU's retail
  price every refresh depending on which one ran last. The check is
  `_is_routed_supplier(decision, mapping.supplier_slug)` against
  `sourcing.resolve_for_sku`'s answer — see
  [ADR-0083](../../../../../../docs/decisions/0083-routed-supplier-cost-and-price-ratchet.md)
  for why, and for the 22 production SKUs (after the Free Fire→NOVA switch,
  [ADR-0082](../../../../../../docs/decisions/0082-nova-steam-and-real-cost-basis.md))
  this is not hypothetical for.
  When the SKU has a saved `margin_percent`, a cost move on the routed
  supplier also re-derives `price_usd`
  (`catalog.admin_service.set_sku_cost_usdt`) so a SKU nobody is actively
  re-pricing never starts selling below cost — see
  [ADR-0050](../../../../../../docs/decisions/0050-sku-margin-percent.md).
  **The price only ratchets up on the automatic path.** `set_sku_cost_usdt`
  takes `allow_price_drop` (default `True`); the hourly/on-demand
  refresh-all path (`price_refresh.refresh_all_mappings`) is the one caller
  that passes `False`, so a supplier cost drop widens the margin instead of
  quietly handing the saving to the customer. A cost rise still raises the
  price either way. The mapping-save route (an operator's own action)
  keeps the default and can still lower a price on purpose. Note that the
  admin's on-demand "Обновить все цены" button also runs through
  `refresh_all_mappings`, so it inherits the same `allow_price_drop=False`
  — it can raise or hold a price, never lower one; a downward correction is
  a per-SKU action only. See
  [ADR-0083](../../../../../../docs/decisions/0083-routed-supplier-cost-and-price-ratchet.md)
  and [the sourcing-by-brand design, §5](../../../../../../docs/superpowers/specs/2026-09-18-sourcing-by-brand-design.md).
- Probe supplier connectivity (`GET /{slug}/health`).
- Resolve a player id to a nickname for the storefront (`player_check.py`),
  behind a per-supplier circuit breaker (`breaker.py`) so a G2B outage costs
  each customer ~150ms rather than the client's full ~15s retry backoff. The
  breaker guards this advisory path only — fulfilment keeps its retry budget,
  see [ADR-0059](../../../../../../docs/decisions/0059-player-check-circuit-breaker.md).
  The check is resolved per **brand** (`check_player_for_brand`,
  `POST /catalog/brands/{slug}/check-player`), not per product. A brand is one
  supplier game (ADR-0079); a brand whose active g2b/game mappings span two
  codes answers `error` and logs `player_check_brand_spans_games`.
- **Import** a G2B game into the catalog (Brand + Product + SKUs + mappings).

## Public interface

Other modules import from `yupay.modules.integrations.api`, never from `service` /
`models` / `routes` directly.

## Import

### Game import

`POST /admin/integrations/g2b/import` (admin-only, `201 GameImportOut`) imports a
G2B **game** into the catalog — the reverse of the SKU-first mapping wizard.
Given a game and a set of denominations it materialises, in one shot, a Brand
(new or reused), a `Product(kind="top_up", supplier_hint="g2b")`, one `Sku` per
denomination, and one `sku_supplier_mapping` per SKU. See
[ADR-0024](../../../../../docs/decisions/0024-g2b-catalog-import.md) and
`docs/architecture/sequence-diagrams/g2b-catalog-import.mmd`.

- **Atomic transaction.** `service.import_game(db, payload, *, admin_id)`
  **flushes only**; the **route commits**. Any error anywhere in the import rolls
  the whole thing back — no half-built Brand can survive a partial import.
- **Backend-computed price, per-row override.** Per denomination:
  `price_usd = price_usd_override if set else round(cost_usdt × (1 + margin_percent/100), 2)`
  (`ROUND_HALF_UP`), where `cost_usdt` is the G2B denomination's `amount`. A
  non-positive computed price is a `422`.
- **Structural idempotency on `sku_code`.** `Sku.sku_code` is globally unique;
  re-importing a denomination whose `sku_code` already exists is **skipped** and
  returned in `skipped[]` rather than erroring. The `Idempotency-Key` header is
  accepted and logged for client convenience, but correctness does not depend on
  it. No extra table, no migration.
- **Auto-created mapping per SKU.** Each imported denomination also gets a
  `sku_supplier_mapping` row: `kind="game"`, `external_product_id=game_code`,
  `external_variant_id=catalogue_name`, `quantity`, `is_active=True`.
- **Translations.** ru/en/uz translations for the Brand and Product are auto-filled
  from the supplier name; the Product's `required_fields` come from the admin
  wizard's `GET …/games/{code}/fields`.
- **No live G2B call.** The endpoint trusts the cost/denominations the wizard
  already fetched; live cost truth stays with the hourly `refresh-all-prices` job.

### `integrations → catalog` dependency

`import_game` calls the catalog **write/admin layer** —
`create_brand` / `create_product` / `create_sku` / `get_brand` plus the
`BrandCreate` / `ProductCreate` / `SkuCreate` / `TranslationIn` schemas — imported
from `catalog.admin_service` / `catalog.admin_schemas` directly (inside the
function) to avoid an import cycle. This is the same pattern
`service.refresh_sku_cost_for_mapping` already uses for `set_sku_cost_usdt`, so
the documented coupling is **`integrations → catalog` (write layer)**.
