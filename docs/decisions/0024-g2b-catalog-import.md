# 0024. Import a G2B game into the catalog via one atomic endpoint in `integrations`

- **Status**: Accepted
- **Date**: 2026-06-04
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data

## Context and problem statement

The existing supplier wizard is **SKU-first**: an operator creates a Brand →
Product → SKU by hand in the catalog admin, then opens the mapping editor and
binds each SKU to a G2B game/denomination (`sku_supplier_mapping`). That is the
right flow when the catalog already exists and we are only attaching a supplier.

Onboarding a *new* game the other way around — starting from what G2B sells and
materialising it into our catalog — was pure manual labour: read G2B's
`games/{code}/catalogue`, hand-create a Brand, a Product, one SKU per
denomination, set a sell price for each, then go back and create one mapping per
SKU. Dozens of clicks per game, easy to get a denomination wrong, and if the
operator gave up halfway they left a half-built Brand with no SKUs in the live
catalog.

We want the **reverse, supplier-first** direction: pick a G2B game, set a
margin, tick the denominations to import, and get a fully wired
Brand + Product + SKUs + supplier mappings in one shot — or nothing at all on
failure.

## Decision drivers

- **Atomicity.** A partial import (Brand with no SKUs, or SKUs with no mappings)
  is worse than no import — it pollutes the live storefront. The whole thing must
  commit or roll back as a unit.
- **Reuse, not reinvention.** The catalog already owns `Brand` / `Product` /
  `Sku` and their write logic; the import must call that, not duplicate it or add
  parallel tables.
- **No new migration.** Onboarding tooling should not change the data model.
- **Pricing is a backend concern.** The sell price is `cost × margin`; computing
  it in the browser invites rounding drift and a tampered-price endpoint.
- **No live-cost coupling.** The import must not become a second place that
  fetches upstream prices — the hourly `refresh-all-prices` job stays the single
  source of cost truth.

## Considered options

1. **Frontend orchestration of the existing CRUD endpoints** — the wizard calls
   `create_brand`, then `create_product`, then N× `create_sku`, then N×
   `upsert_mapping` from the browser.
2. **A dedicated import/staging table + reconciliation job** — write the request
   to a new `catalog_imports` table and have a worker fan it out into the catalog.
3. **One atomic `POST /admin/integrations/g2b/import`** in `integrations` that
   orchestrates the catalog write layer inside a single DB transaction.

## Decision outcome

**Chosen option: Option 3.** A new admin-only endpoint
`POST /admin/integrations/g2b/import` (`integrations.routes.import_g2b_game`)
delegates to `integrations.service.import_game(db, payload, *, admin_id)`, which:

- creates (`new_brand`) or reuses (`brand_id`) a `Brand`, then a
  `Product(kind="top_up", supplier_hint="g2b")` whose `required_fields` come from
  the wizard's `GET …/games/{code}/fields` call;
- for each requested denomination creates a `Sku` and a `sku_supplier_mapping`
  row (`kind="game"`, `external_product_id=game_code`,
  `external_variant_id=catalogue_name`, `quantity`, `is_active=True`);
- auto-fills ru/en/uz translations from the supplier name across all three
  locales in the same call.

**Transaction boundary.** The service **flushes only**; the **route commits**
(and the route's error mapping handles 404/409/422). Any exception anywhere in
the loop aborts the request and the session rolls back — no half-built Brand can
survive.

**Pricing.** Computed backend-side per denomination:
`price_usd = price_usd_override if set else round(cost_usdt × (1 + margin_percent/100), 2)`
with `ROUND_HALF_UP`, where `cost_usdt` is the G2B denomination's `amount`. A
non-positive computed price is a `422`. The per-row override lets the operator
pin an exact price where margin maths is not wanted.

**Idempotency is structural.** `Sku.sku_code` is globally unique; before the loop
the service selects the existing codes and re-importing a denomination whose
`sku_code` already exists is **skipped** (returned in `skipped[]`) rather than
erroring. The `Idempotency-Key` header is accepted for client convenience and
logged, but correctness does not depend on it. No new table, no migration.

**No live G2B call.** The endpoint trusts the cost/denominations the admin wizard
already fetched; it never calls G2B itself. Live cost truth stays with the hourly
`integrations.price_refresh.refresh_all_mappings` job.

To avoid an `integrations ↔ catalog` import cycle, the service imports the
catalog write surface (`create_brand` / `create_product` / `create_sku` /
`get_brand` and the matching `BrandCreate` / `ProductCreate` / `SkuCreate` /
`TranslationIn` schemas) from `catalog.admin_service` / `catalog.admin_schemas`
directly — the same pattern `integrations.service.refresh_sku_cost_for_mapping`
already uses for `set_sku_cost_usdt`.

### Positive consequences

- One click materialises a fully wired, immediately sellable game; nothing
  survives a mid-import failure.
- No new tables or migration — the import reuses the catalog's existing model.
- The admin gains a supplier **catalog browser**
  (`SupplierCatalogPage`, `/integrations/:slug/catalog`) and a 3-section
  **import wizard** (`GameImportPage` + `DenominationTable`,
  `/integrations/:slug/catalog/:gameCode`), reachable from a "Перейти к каталогу"
  action on `G2bDetailPage`.
- Re-running an import to add newly listed denominations is safe — existing ones
  are skipped, not duplicated or failed.

### Negative consequences

- A new **`integrations → catalog` (write/admin layer)** dependency. Acceptable:
  it is the same coupling the cost-refresh path already carries, kept acyclic by
  importing `catalog.admin_*` lazily inside the function.
- `import_game` is a multi-entity orchestrator that crosses a module boundary by
  design; it is necessarily larger than a single-table service function.
- Voucher (gift-card) import is **out of scope** here — only games
  (`kind="game"` mappings) are imported. Voucher import is deferred.

## Validation

- `apps/api/tests/integration/` covers `import_game`: happy path (Brand +
  Product + N SKUs + N mappings created, sell price = `cost × (1+margin)` and the
  per-row override honoured), the structural-skip path (re-import returns the
  duplicate `sku_code` in `skipped[]` and creates nothing new), and the
  rollback path (an error mid-loop leaves zero rows — no orphan Brand).
- Endpoint returns `201` with `GameImportOut {brand_id, product_id, created_skus,
  created_mappings, skipped}`.

## Alternatives considered (detail)

### Option 1 — frontend orchestration of existing CRUD endpoints

The browser would fire Brand, Product and per-denomination Sku/mapping calls in
sequence. Rejected: **not atomic.** A network blip or a `409` on the third SKU
leaves a partial Brand/Product live in the storefront, and the client has no way
to roll the earlier writes back. It also pushes price computation into the
browser, contradicting the "pricing is a backend concern" driver.

### Option 2 — dedicated import/staging table + reconciliation worker

A `catalog_imports` table plus a worker that fans the request out into the
catalog. Rejected: it adds a migration and a new table for no benefit — the
import is small, synchronous, and naturally fits one request-scoped transaction.
Staging buys durability we do not need and adds an eventual-consistency window
where the catalog and the staged request disagree.

## References

- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — catalog three-level model + form schema
- [ADR-0019](./0019-g2b-integration.md) — G2B supplier integration
- `docs/architecture/sequence-diagrams/g2b-catalog-import.mmd`
- `apps/api/src/yupay/modules/integrations/README.md`
