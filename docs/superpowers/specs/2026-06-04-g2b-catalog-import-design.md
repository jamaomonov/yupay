# Design: G2B supplier-catalog browser + import games → brand/SKU

**Date:** 2026-06-04
**Status:** Approved (brainstorming) — pending implementation plan
**Scope:** Admin SPA (`apps/admin`) + API (`apps/api`, `integrations` + `catalog` modules)

---

## 1. Problem

Today the admin can only map **from an existing YuPay SKU** to a supplier item
(`/integrations/mappings/new`, a 5-step SKU-first wizard). There is no way to go the
**other direction**: browse the G2B supplier catalog, open a game, see its denominations,
and pull that game into our catalog as a Brand + Product + SKUs ready to sell.

Operators want: a **"Перейти к каталогу"** entry point → browse all G2B games → open a game →
see its denominations → **import the game as one of our brands/products** and its
**denominations as our SKUs**, with the supplier mapping created automatically so the new
SKUs are immediately fulfillable through G2B.

## 2. Goals / Non-goals

**Goals**

- Browse the cached G2B game catalog from the admin, with search and an "already imported" badge.
- Open a game and preview its denominations (live from G2B) and required player fields.
- Import a game in one atomic action: create (or attach to) a Brand, create a Product
  (`kind=top_up`), create N SKUs, and create N `sku_supplier_mapping` rows — all or nothing.
- Compute sell price from a margin on the backend; allow per-row overrides.
- Auto-fill translations (ru/en/uz) and `required_fields` from G2B; admin edits later in the
  catalog section.

**Non-goals (follow-up)**

- Importing **vouchers** (only games in v1).
- Uploading denomination artwork during import (only optional `image_url`; edit in SKU later).
- Re-verifying denominations/cost against G2B inside the import endpoint (the admin-only
  frontend already fetched them; the endpoint trusts its own UI — see §6).
- Admin i18n: the admin SPA is Russian-only (hardcoded strings, no `@yupay/i18n`), so the
  3-locale parity rule that applies to `web`/`miniapp` does **not** apply here.
- No new DB tables → **no Alembic migration**. Reuses `brands`, `products`, `skus`,
  `sku_supplier_mapping`, `supplier_catalog_cache`.

## 3. User flow

```
G2B detail (/integrations/g2b)
  └─ card "Каталог поставщика" → button "Перейти к каталогу"
       ↓
Supplier catalog  (/integrations/g2b/catalog)              ← NEW page
  • table of all games from supplier_catalog_cache (kind='game'), debounced search
  • "уже импортирована" badge when game_code already appears in mappings (kind=game)
  • row → "Импортировать →"
       ↓
Game import wizard  (/integrations/g2b/catalog/:gameCode)  ← NEW page
  Step 1 — Назначение:  ◉ Новый бренд   ○ Существующий бренд [Combobox /admin/catalog/brands]
  Step 2 — Бренд + продукт: slug (auto from game_code, editable), ru name (prefilled from G2B),
           category <select>, margin % (default 20). Preview required_fields from /games/{code}/fields.
  Step 3 — Номиналы: table from /games/{code}/catalogue
           [✓] | Номинал | Себест. $ | Цена прод. $ (live = cost×(1+margin), editable→override) | sku_code (auto, editable)
  Submit → POST /admin/integrations/g2b/import (Idempotency-Key) → toast → navigate to /brands/:id
```

**Decision:** one game = one Product (`kind=top_up`) holding all denominations as SKUs,
inside one Brand (new or existing). Not a brand-per-denomination.

## 4. Backend

### 4.1 New endpoint

`POST /admin/integrations/g2b/import` — admin-only, accepts `Idempotency-Key` (AGENTS.md §9).
Lives in the `integrations` module (it owns supplier concerns) and orchestrates the `catalog`
module through its **public surface** (see §4.3).

**Request — `GameImportIn`:**

```python
class NewBrandIn(BaseModel):
    slug: str            # ^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$
    category_id: str
    name: str            # → auto-filled into ru/en/uz brand translations
    logo_url: str | None = None
    hero_image_url: str | None = None
    accent_color: str | None = None

class ProductImportIn(BaseModel):
    slug: str            # ^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$
    name: str            # → auto ru/en/uz product translations
    required_fields: list[FormField] = Field(default_factory=list)   # built by FE from G2B
    image_url: str | None = None

class DenomImportIn(BaseModel):
    catalogue_name: str                  # → mapping.external_variant_id
    denomination: str                    # SKU label, e.g. "60 UC"
    sku_code: str                        # unique, ^[A-Za-z0-9._-]+$
    cost_usdt: Decimal = Field(gt=0)     # = G2B amount
    price_usd_override: Decimal | None = Field(default=None, gt=0)
    region: str | None = None
    quantity: int = Field(default=1, ge=1)

class GameImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_code: str                       # → mapping.external_product_id
    target: Literal["new_brand", "existing_brand"]
    brand_id: str | None = None          # required when target == existing_brand
    new_brand: NewBrandIn | None = None  # required when target == new_brand
    product: ProductImportIn
    margin_percent: Decimal = Field(ge=0, le=1000)   # e.g. 20 → +20%
    denominations: list[DenomImportIn] = Field(min_length=1)
```

A model validator enforces: `target=new_brand ⇒ new_brand is not None`;
`target=existing_brand ⇒ brand_id is not None`.

**Pricing (backend):**

```
price_usd = price_usd_override            if provided
            else round(cost_usdt * (1 + margin_percent / 100), 2)
```

If the computed `price_usd <= 0` → `422` naming the offending `sku_code`.

**Response — `GameImportOut`:**

```python
class GameImportOut(BaseModel):
    brand_id: str
    product_id: str
    created_skus: int
    created_mappings: int
    skipped: list[str]   # sku_codes that already existed (re-import)
```

### 4.2 Service logic (`integrations.service.import_game`) — single transaction

1. Resolve brand: `target=new_brand` → `catalog.create_brand(BrandCreate(... translations=name×3))`;
   else load + validate `brand_id` exists.
2. `catalog.create_product(ProductCreate(brand_id, kind="top_up", supplier_hint="g2b",
required_fields=..., translations=name×3, slug=...))`.
3. For each denomination:
   - compute `price_usd` (see pricing);
   - if `sku_code` already exists → append to `skipped`, continue;
   - `catalog.create_sku(SkuCreate(product_id, sku_code, denomination, region, price_usd, cost_usdt, ...))`;
   - `integrations.upsert_mapping(MappingUpsert(sku_id, supplier_slug="g2b", kind="game",
external_product_id=game_code, external_variant_id=catalogue_name, quantity, updated_by=admin.id))`.
4. `await db.commit()` once. Any exception → no commit → full rollback (catalog create\_\* and
   upsert_mapping only `flush()`, never commit themselves — verified).

**Errors:** duplicate `brand.slug` / `product.slug` → `409` with the offending slug in `detail`;
unknown `brand_id` / `category_id` → `404`; validation → `422`.

### 4.3 Module-boundary change

`catalog/api.py` currently re-exports only **read** helpers. Extend it to expose the write path
the importer needs, so `integrations` depends on `catalog`'s **public** surface (not the private
`admin_service`):

- re-export `create_brand`, `create_product`, `create_sku` from `catalog.admin_service`;
- re-export `BrandCreate`, `ProductCreate`, `SkuCreate`, `TranslationIn` from `catalog.admin_schemas`.

This adds an explicit, documented `integrations → catalog (write API)` dependency.

### 4.4 "Already imported" signal

No new endpoint. The catalog browser fetches existing mappings
(`GET /admin/integrations/mappings?supplier_slug=g2b`), builds a `Set` of
`external_product_id` where `kind=game`, and badges matching rows.

### 4.5 required_fields mapping

The frontend calls `GET /admin/integrations/g2b/games/{code}/fields` (returns `list[str]`,
e.g. `["userid","zoneid"]`), maps each to a `FormField` (`key`=string, `label` = ru/en/uz from a
small dictionary of common G2B field names, fallback to the raw key, `type="text"`), shows a
preview, and includes the result in `product.required_fields`. The backend stores it verbatim.

## 5. Frontend (admin SPA)

**New files** (`apps/admin/src/features/integrations/`)

- `SupplierCatalogPage.tsx` — route `/integrations/g2b/catalog`. `DataTable` of games from
  `GET /catalog?supplier_slug=g2b&kind=game`; debounced `?search=`; imported badge; empty state
  ("Сначала синхронизируйте каталог" → link back to G2B detail).
- `GameImportPage.tsx` — route `/integrations/g2b/catalog/:gameCode`. `react-hook-form` + `zod`,
  3 steps as described in §3. Submit → `POST /admin/integrations/g2b/import` with
  `Idempotency-Key` (`crypto.randomUUID()`); on success toast + `navigate(/brands/:id)`.

**Edited files**

- `G2bDetailPage.tsx` — add a second button **"Перейти к каталогу"** (`Link` → `/integrations/g2b/catalog`)
  in the existing "Каталог поставщика" card, beside "Синхронизировать".
- `app/router.tsx` — two new routes under the authed `Layout`.
- `lib/queryKeys.ts` — add `gameDenoms(code)`, `gameFields(code)` (reuse existing `integrationCatalog`).
- `features/integrations/types.ts` — `GameImportIn` / `GameImportOut`; reuse `GameDenomRow`.

**Conventions:** `PageHeader`, `DataTable`, `Field`, `Combobox`, `Button` (`@yupay/ui`),
`useToast`, CSS variables. No new dependencies. Errors formatted via the existing `ApiError`
→ `detail/title` pattern.

## 6. Trust boundary

The import endpoint does **not** call G2B live; it persists the cost/denominations the admin
UI already fetched. This is intentional: it is an authenticated **admin-only** tool, keeps the
endpoint a pure DB transaction (simpler, fully unit-testable without respx), and the source of
truth for live fulfilment cost remains the hourly `refresh-all-prices` job over
`sku_supplier_mapping`, which re-reads G2B after import.

## 7. Testing (AGENTS.md §8)

Touches `catalog` + `integrations` (not payments/wallet/fulfilment) → coverage gate **≥80%**.

**Integration** — `apps/api/tests/integration/test_g2b_import.py` (testcontainers Postgres):

- import into **new brand** → Brand(+3 locales) + Product(top_up, required_fields) + N SKUs +
  N mappings; prices = `cost×(1+margin)`.
- import into **existing brand** → new Product under `brand_id`; brand not duplicated.
- pricing: `price_usd_override` wins; otherwise margin formula.
- idempotent re-import (same `sku_code`) → `skipped[]`, no duplicates.
- errors: taken `brand.slug`/`sku_code` → `409`; `cost×margin ≤ 0` → `422`; unknown
  `brand_id`/`category_id` → `404`.
- mapping correctness: `external_product_id=game_code`, `external_variant_id=catalogue_name`,
  `kind=game`.

**Frontend:** admin SPA has no established unit-test suite; verify with `tsc` (0 errors) +
manual run: sync catalog → import a game → brand appears in `/brands`, SKUs in `/skus`, mapping
in `/integrations/mappings`.

## 8. Documentation (AGENTS.md §5)

- `make gen-api` → regenerate `docs/api/openapi.json` + `packages/api-client/`; note the new
  endpoint + its idempotency in `docs/api/README.md`.
- ADR `docs/decisions/0024-g2b-catalog-import.md` (MADR) — atomic endpoint in `integrations`,
  reuse of `catalog` public write API, backend margin.
- `docs/architecture/sequence-diagrams/g2b-catalog-import.mmd` (Mermaid).
- `docs/architecture/module-map.md` — record `integrations → catalog (write API)`.
- `apps/api/src/yupay/modules/integrations/README.md` — add an "Import" section.

## 9. Definition of Done

- [ ] `POST /admin/integrations/g2b/import` implemented; atomic; idempotent on `sku_code`.
- [ ] Margin computed backend-side with per-row override; `≤0` rejected.
- [ ] Supplier mapping auto-created per SKU.
- [ ] `catalog/api.py` extended with the write surface; `integrations` imports through it.
- [ ] Admin: catalog browser page + import wizard + "Перейти к каталогу" button + 2 routes.
- [ ] Integration tests green; coverage ≥80% on new code.
- [ ] OpenAPI regenerated; TS client regenerated; no drift.
- [ ] ADR + sequence diagram + module-map + integrations README updated.
- [ ] `make lint typecheck test` green; admin `tsc` green.
- [ ] Manual run verified (brand/SKU/mapping created).
