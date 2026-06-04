# `integrations` module

Owns the SKU↔supplier wiring: the `sku_supplier_mapping` table (the source of
truth for _what_ a supplier should sell when the fulfilment saga routes a SKU
through them), a `supplier_catalog_cache` that backs admin autocomplete, supplier
health probes, and supplier-cost refresh. Supplier adapter code itself lives in
`fulfillment/suppliers/*`.

## Responsibilities

- Own `sku_supplier_mapping` and `supplier_catalog_cache`.
- Serve the admin CRUD over mappings and the cached supplier catalog.
- Refresh `Sku.cost_usdt` from the supplier (on upsert and via the hourly
  `refresh-all-prices` job — the single source of cost truth).
- Probe supplier connectivity (`GET /{slug}/health`).
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
