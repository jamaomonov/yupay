# `integrations` module

Owns the SKU↔supplier wiring: the `sku_supplier_mapping` table (the source of
truth for _what_ a supplier should sell when the fulfilment saga routes a SKU
through them), a `supplier_catalog_cache` that backs admin autocomplete, supplier
health probes, and supplier-cost refresh. Supplier adapter code itself lives in
`fulfillment/suppliers/*`.

## Responsibilities

- Own `sku_supplier_mapping` and `supplier_catalog_cache`.
- Serve the admin CRUD over mappings and the cached supplier catalog.
- **Sync a supplier's catalogue into `supplier_catalog_cache`** so the mapping
  wizard's "ID сервиса у поставщика" / "ID номинала у поставщика" fields can
  be a picker instead of an operator typing an id they'd otherwise have to
  call the supplier's own API to discover.
  `POST /admin/integrations/{supplier}/sync-catalog` (`g2b | nova | gengine`,
  the same route the hourly `sync_supplier_catalog` scheduler job calls) does
  the whole-catalogue sweep — every `voucher`/`game` row, best-effort, never
  raises. `catalog_sync.py` is a thin dispatcher; the actual per-supplier
  logic lives one module each (`catalog_sync_g2b.py`, `catalog_sync_nova.py`,
  `catalog_sync_gengine.py` — split out when three suppliers would have
  pushed a single file past AGENTS.md §6's 400-LOC limit, the same seam
  `sourcing/brand_overview.py` and `cost_lookup.py` were split out on) behind
  the shared `CatalogSyncReport` type in `catalog_sync_types.py`.

  **Every supplier here has two catalogues**, and both are swept (ADR-0090).
  G2B sells flat vouchers beside its games. NOVA sells top-up categories
  (`/api/v2/topups`) beside gift-card categories (`/api/v2/giftcards`, whose
  cards carry their own `card_id`, price and stock). G-Engine sells recharge
  services (`/recharge/services`) beside shop products (`/shop/products`).
  The second catalogue of each of the last two was added on 2026-09-21, after
  an operator reported that NOVA's sync refreshed only games and that
  G-Engine's catalogue was permanently unsynced — it had never been read at
  all. The gift-card halves live in `catalog_sync_nova_vouchers.py` and
  `catalog_sync_gengine_vouchers.py`.

  **Mind the id namespaces.** G-Engine's shop product `9` is Roblox Global;
  its recharge service `9` is Delta Force. They are told apart by cache
  `kind` alone, which is why a voucher's ladder is `voucher_denom` and not a
  reused `game_denom` (migration 0086).

  **Denominations (`game_denom`, `voucher_denom`) are never swept wholesale** —
  only synced
  for a product an active mapping already points at (`svc.mapped_external_product_ids`),
  the same restriction the pre-existing G2B mapped-voucher refresh applies to
  vouchers. Reading a game's denominations costs a separate upstream call per
  game for every supplier except G-Engine, whose `GET /recharge/services`
  already returns each service's denominations inline — so its mapped-only
  filter costs nothing extra, it just declines to cache the unmapped ones.
  For a product the cache has never seen, `POST
/admin/integrations/{supplier}/games/{game_id}/sync-denominations` — or its
  voucher twin `POST /admin/integrations/{supplier}/vouchers/{product_id}/sync-denominations`
  — (`nova | gengine`; G2B keeps its own pre-existing live picker,
  `GET /g2b/games/{game_code}/catalogue`, uncached, and its vouchers really
  are flat so there is no ladder to pull) pulls exactly that one
  product's denominations in, on demand — a `POST`, explicitly triggered by an
  operator, off the order path: the deviation-free shape AGENTS.md §10 asks
  for, not a violation of it. `GET /admin/integrations/catalog` itself never
  calls a supplier; it only ever reads what one of the two sync routes (or
  the hourly job) already wrote, filtering `game_denom` rows to one game via
  `parent_external_id`.

- Refresh a supplier's price for a mapping (on upsert and via the hourly
  `refresh-all-prices` job), **dispatched by `mapping.supplier_slug`**
  (`cost_refresh.refresh_sku_cost_for_mapping`, split out into its own module
  when `service.py` passed 900 lines. The per-supplier raw-price lookups it
  dispatches into live in `cost_lookup.py` in turn, split out of
  `cost_refresh.py` when that module itself passed 495 lines — G2B reads the
  catalog cache or calls `games_catalogue` live; NOVA calls
  `GET /topups/offers` per category, cached per refresh run so a 19-SKU
  brand makes one call, not nineteen; a NOVA Steam mapping is skipped, it
  has no catalogue price to look up; a NOVA **gift-card** mapping reads the
  cache instead, because its price lives in the other catalogue and the
  top-up endpoint would 404 on a perfectly real category id; G-Engine reads
  the cache for both of its catalogues, since the sync already holds every
  number it would otherwise re-fetch per mapping).
  So for G-Engine and for NOVA gift cards, **«Синхронизировать каталог» is
  the button that moves the price** — a stale cache is a stale cost. That
  coupling is deliberate (ADR-0090); the alternative was ~120 redundant
  upstream calls an hour.
  **Only the supplier a SKU actually routes to may write `Sku.cost_usdt`.**
  Every other active mapping still gets refreshed — it just records a
  `supplier_price_history` row and touches nothing else. `Sku.cost_usdt` is
  our cost basis, not a fact about a supplier: retail price derives from it,
  an order line freezes it at checkout, the margin report subtracts it, so
  two suppliers writing it on the same SKU would flip that SKU's retail
  price every refresh depending on which one ran last. The check is
  `is_routed_supplier(decision, mapping.supplier_slug)` against
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
