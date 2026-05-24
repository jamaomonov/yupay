# 0009. Catalog: three levels + per-product form schema

- **Status**: Accepted
- **Date**: 2026-05-15
- **Supersedes**: shape established in ADR-0006 + initial migration
- **Deciders**: founding team
- **Tags**: backend, catalog, data-model

## Context

The initial catalog (migration 0003) had two real levels: `Product → SKU`. That works
when each product is a single, monolithic item ("Steam Wallet"). It falls apart the
moment a single game (PUBG Mobile) sells several distinct products (UC, Royal Pass,
Skin Pack) that share branding, hero image, and SEO copy but differ in form schema and
fulfilment behaviour. With only two levels we'd either:

1. Duplicate the brand metadata across every product (Spotify Premium 1mo, Spotify
   Premium 3mo, Spotify Premium 12mo each carrying the Spotify lockup, slug prefix,
   intro copy) — denormalised and fragile, or
2. Cram several distinct items into one product and lose the ability to model
   per-item form fields (player ID, server, region) and per-item supplier routing.

Both are wrong. Additionally, top-up products need a _form schema_ the storefront can
render: PUBG asks for `player_id`, Spotify asks for an account email, USDT asks for a
wallet address. We need this schema to be **data**, not code, so adding a new
top-up doesn't require a frontend release.

## Decision

Catalog moves to **three levels**:

```
Category   (games / subscriptions / gift-cards / crypto)
└── Brand    (PUBG Mobile, Steam, Spotify, Apple, USDT — the thing customers recognise)
    └── Product   (UC, Royal Pass, Wallet code, Premium subscription — what they actually buy)
        ├── required_fields jsonb   (schema of inputs the storefront must collect)
        └── SKU                     (60 UC TR, 60 UC RU, 1 month — concrete priced position)
```

A **Brand** owns the marketing surface (name, hero image, description, slug, primary
category). A **Product** owns the buying contract (what kind of fulfilment, what
inputs to collect, what SKUs are available). A **SKU** is a single sellable line:
denomination + region + price.

### `required_fields` shape

The schema is a JSON array of field descriptors. Stored in
`products.required_fields jsonb NOT NULL DEFAULT '[]'`. The storefront iterates it
and renders a typed form; the API validates against the same schema on order creation.

```jsonc
[
  {
    "key": "player_id",
    "label": { "ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID" },
    "type": "text",
    "required": true,
    "placeholder": { "ru": "12345678" },
    "pattern": "^[0-9]{6,12}$",
    "help_text": { "ru": "Найди ID в настройках профиля игры" },
  },
  {
    "key": "server",
    "label": { "ru": "Сервер", "en": "Server", "uz": "Server" },
    "type": "select",
    "required": true,
    "options": [
      { "value": "AS", "label": { "ru": "Азия", "en": "Asia" } },
      { "value": "EU", "label": { "ru": "Европа", "en": "Europe" } },
      { "value": "NA", "label": { "ru": "Сев. Америка", "en": "North America" } },
    ],
  },
]
```

Supported `type` values at MVP: `text`, `email`, `number`, `select`. New types are
added by extending the validator + the storefront's form renderer together.

### Brand → Category cardinality

A brand belongs to exactly **one** category. This keeps navigation simple ("Spotify
in Subscriptions", never "Spotify in Subscriptions _and_ Gift Cards"). If a real
counter-example appears, we add a join table later — but it is not in scope today.

### SKU stays single-region

Region remains on `SKU`, not on `Product`. The same product (PUBG UC) can have SKUs
in TR, RU, and KZ regions; pricing and supplier routing differ per region.

## Consequences

- One brand row per actually-distinct vendor; product copy stays DRY.
- Adding "PUBG Royal Pass" is one new `products` row + its `required_fields` + SKUs.
  No new schema, no new code.
- The storefront's form-rendering layer is data-driven — `apps/web` and `apps/miniapp`
  share the same renderer.
- The `categories` table loses its direct edge to `products` — products inherit
  category via their brand. We **drop** `products.category_id`.
- Existing migration `0003_catalog_init` stays as-is; the change lands in
  `0004_catalog_brands` so the audit trail is clean.

## Alternatives considered

- **Stay at two levels, denormalise brand fields onto products** — rejected: every
  copy update is a multi-row UPDATE, hero images drift, SEO breaks.
- **Polymorphic "entity" supertype** with brand/product collapsed into one
  configurable shape — over-engineered, hard to query.
- **Schema-less product attributes** (one `attributes jsonb` on Product covering
  brand fields + form fields + everything else) — rejected: typed columns are worth
  the friction for fields the storefront and the API both depend on.

## References

- [ADR-0002 — modular monolith](./0002-use-modular-monolith.md)
- [`apps/api/src/yupay/modules/catalog/`](../../apps/api/src/yupay/modules/catalog)
- [`apps/api/migrations/versions/0004_catalog_brands.py`](../../apps/api/migrations/versions/0004_catalog_brands.py)
