# `catalog` module

Three-level read-only product catalog: **Category → Brand → Product → SKU**, with
per-product form schema and per-currency price overrides. See
[ADR-0009](../../../../../docs/decisions/0009-catalog-three-level-plus-form-schema.md).

## Responsibilities

- Own the catalog tables and serve them as a localised, currency-aware read API.
- Carry the storefront's form schema (`Product.required_fields`) so adding a new
  top-up doesn't require a frontend release.
- Resolve display prices: **override → FX → USD-only** per SKU.
- Provide seed data so a fresh dev stack has something to render.

## Levels

| Level        | Meaning                                                | Example                                                   |
| ------------ | ------------------------------------------------------ | --------------------------------------------------------- |
| **Category** | Top-level grouping shown on the homepage               | "Games", "Subscriptions", "Gift cards", "Crypto"          |
| **Brand**    | What customers recognise — a game / service / vendor   | "PUBG Mobile", "Steam", "Spotify", "Apple", "USDT"        |
| **Product**  | A buyable item of that brand, with its own form schema | "UC", "Royal Pass", "Wallet code", "Premium subscription" |
| **SKU**      | A concrete priced position (denomination + region)     | "60 UC TR", "60 UC AS", "500 RUB RU"                      |

## Visibility cascade (`active` flags)

Every level carries an `active` boolean, and visibility **cascades downward**:
a row is served by the read API only when it and every ancestor are active.
Hiding a `Category` hides all its brands, their products, and their SKUs;
hiding a `Brand` hides its products and SKUs; and so on. This holds on **every**
read path — the listings *and* the by-slug / by-id detail lookups — so a
staged-but-hidden ancestor can never leak a descendant by direct slug (nor let
checkout price a SKU whose category or brand is turned off). `Brand.maintenance`
is separate: it keeps the brand *visible* but blocks purchases (a "maintenance"
badge), whereas `active=False` removes it entirely. This is the staging pattern
used to prepare a launch (e.g. Steam) before flipping it live.

## Public interface

```python
from yupay.modules.catalog.api import (
    Brand, Category, Product, Sku, SkuPrice,             # ORM types
    BrandListOut, BrandDetailOut, BrandOut,              # DTOs
    CategoryListOut, ProductListOut,
    ProductDetailOut, ProductSummaryOut, SkuOut,
    PriceOut, FormField, FormOption, LocaleMap,
    get_brand_by_slug, get_product_by_slug, get_sku_by_id,
    list_brands, list_categories, list_products,
    router,                                              # FastAPI router @ /api/v1/catalog
)
```

## Tables owned

| Table                                 | Notes                                                                              |
| ------------------------------------- | ---------------------------------------------------------------------------------- |
| `categories`, `category_translations` | Flat list                                                                          |
| `brands`, `brand_translations`        | FK → categories (1:N). Logo, hero image, accent colour                             |
| `products`, `product_translations`    | FK → brands (1:N). `kind ∈ {top_up, voucher}`. `required_fields jsonb` form schema |
| `skus`                                | FK → products (1:N). `price_usd` canonical; ≥ 0 enforced                           |
| `sku_prices`                          | Per-currency override; composite PK `(sku_id, currency)`                           |

## HTTP surface

| Method | Path                                                                   | Returns                                              |
| ------ | ---------------------------------------------------------------------- | ---------------------------------------------------- |
| `GET`  | `/api/v1/catalog/categories`                                           | `CategoryListOut` (localised)                        |
| `GET`  | `/api/v1/catalog/brands?category=<slug>`                               | `BrandListOut`                                       |
| `GET`  | `/api/v1/catalog/brands/{slug}?currency=<RUB>`                         | `BrandDetailOut` (brand + summaries of its products) |
| `GET`  | `/api/v1/catalog/products?category=<slug>&brand=<slug>&currency=<RUB>` | `ProductListOut`                                     |
| `GET`  | `/api/v1/catalog/products/{slug}?currency=<RUB>`                       | `ProductDetailOut` (brand + form schema + SKU list)  |
| `GET`  | `/api/v1/catalog/skus/{sku_id}?currency=<RUB>`                         | `SkuOut` (used by checkout)                          |

`Accept-Language` resolves the locale (`ru` default, `en`, `uz`). `?currency=` activates
display-price resolution; unsupported codes silently fall back to USD-only.

## Form schema (`required_fields`)

Each `Product` carries a list of field descriptors that the storefront renders into a
typed form, and that the API validates on order creation.

```jsonc
[
  {
    "key": "player_id",
    "label": { "ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID" },
    "type": "text",
    "required": true,
    "pattern": "^[0-9]{6,20}$",
    "placeholder": { "ru": "12345678", "en": "12345678" },
  },
  {
    "key": "server",
    "label": { "ru": "Сервер", "en": "Server" },
    "type": "select",
    "required": true,
    "options": [
      { "value": "as", "label": { "ru": "Азия", "en": "Asia" } },
      { "value": "eu", "label": { "ru": "Европа", "en": "Europe" } },
    ],
  },
]
```

Supported `type` values at MVP: `text`, `email`, `number`, `select`. Adding a new type
requires extending the `FormField` schema **and** the storefront's form renderer.

### The `check` descriptor

A field may carry an optional `check` object that opts it into the storefront's
player-id verification lookup (a "Проверить" button that resolves the id to an
account nickname before the customer pays — see
[ADR-0031](../../../../../docs/decisions/0031-storefront-player-check.md)):

```jsonc
{
  "key": "player_id",
  "label": { "ru": "ID игрока", "en": "Player ID" },
  "type": "text",
  "pattern": "^[0-9]{6,20}$",
  "check": {
    "provider": "g2b", // which checker backs this field
    "server_field": "server", // optional: key of the sibling field supplying server_id
  },
}
```

`check` opts the field into the storefront nickname lookup (`POST
/api/v1/catalog/products/{id}/check-player`); it is advisory only and never
gates checkout. `provider` may also be `"waxpeer"` — that branch validates a
Steam login instead of resolving a game player id, and returns no nickname
(`name` is always `null`).

## Display-price policy

For every SKU and a requested currency `Q`:

1. `Q == "USD"` → return `price_usd` (source = `"usd"`).
2. Explicit `sku_prices` row exists → return that (source = `"override"`).
3. FX module available → convert via `fx.convert(price_usd, USD, Q)` (source = `"fx"`).
   FX failures are **swallowed per-SKU** so a single unreachable rate doesn't blank
   a whole listing.
4. Otherwise → omit `display_price` (client falls back to `price_usd`).

## Seed data

```bash
docker compose exec api python -m yupay.scripts.seed_catalog
```

Inserts 4 categories, 5 brands (PUBG Mobile, Steam, Spotify, Apple, USDT), 6 products
(UC + Royal Pass, Wallet, Premium, Gift Card, TRC-20), 21 SKUs with realistic
regional pricing. Idempotent — re-running matches by `slug` / `sku_code`.

## Tests

- `apps/api/tests/unit/test_catalog_service.py` — translation fallback, override → FX
  → USD-only resolution, identity passthrough.
- `apps/api/tests/integration/test_catalog_routes.py` — all 6 endpoints against a real
  Postgres, including brand → products navigation, `required_fields` carriage,
  `RUB` override + degradation on a broken FX chain, unsupported currency.

## What's deliberately **not** here yet

- **Search & filters** (price range, region, tags). Full-text search lands with Meilisearch.
- **Inventory awareness.** Stock counts come from the `inventory` module.
- **Admin CRUD**. Content is loaded via `seed_catalog` until the admin panel arrives.
