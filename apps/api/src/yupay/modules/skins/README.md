# `skins` module

CS2 skins (ADR-0093): our own item catalogue from ByMykel/CSGO-API, Waxpeer's
`auto` listings folded onto it every five minutes, and the read API the
storefront browses. Buying one offer is `checkout.py` (pricing the order line) plus the
`waxpeer_skins` fulfiller and `fulfillment/skin_sweeps.py` (tracking the Steam trade) — see
`docs/product/flows/skins-buy.md` and `docs/runbooks/skins-purchase.md`.

## Responsibilities

- Own `skin_items` (one row per market hash name + Doppler phase, plus two
  per-item pricing overrides), `skin_pricing_rules` (row 1: the pricing
  document — expenses, brackets per channel, liquidity bands, category and
  weapon adjustments, min margin, floor, UZS rounding, Steam cap) and
  `skin_search_aliases`.
- Parse market hash names deterministically (`naming.py`) so a Waxpeer
  name with an inline phase lands on the ByMykel row.
- Import the catalogue daily (`bymykel.py`) and prices every five minutes
  (`prices.py`) — both run from `apps/scheduler`, never in the api process.
- Serve `/skins/catalog`, `/skins/facets`, `/skins/suggest`, `/skins/{slug}`
  from Postgres + Redis, and `/skins/{slug}/listings` through a rate-budgeted,
  cached, degradable proxy to Waxpeer (the §10 carve-out).

Every public route 404s while `cs2_skins_enabled` is off; both jobs are
no-ops while `cs2_skins_sync_enabled` is off.

## Storefront

Web pages (plan `docs/superpowers/plans/2026-09-28-cs2-skins-storefront.md`):
`apps/web/src/app/[locale]/skins/page.tsx` (catalogue — filters live in the URL,
server-rendered) and `skins/[slug]/page.tsx` (item — wear tiles, live listings loaded
from the browser). Nav/footer/sitemap entries appear only with `SKINS_ENABLED=true` in
the web env (`apps/web/src/lib/features.ts`). Flow: `docs/product/flows/skins-browse.md`.
Mini app (plan `docs/superpowers/plans/2026-09-28-cs2-skins-miniapp.md`): `/cs2-market` and
`/cs2-market/:slug` (`apps/miniapp/src/pages/CS2SkinMarket.tsx`, `CS2Skin.tsx`), gated only
by this API's flag.

Buying (plan `docs/superpowers/plans/2026-09-29-cs2-skins-purchase-ui.md`): the item
page shows the buy panel only when `GET /skins/{slug}` names `buy_sku_id` (the `cs2-skin`
SKU is seeded and active). Web: `components/skins/SkinBuyPanel.tsx` + `lib/skin-checkout.ts`,
order page `components/order/SkinTradeCard.tsx`. Mini app: `components/skins/SkinBuyPanel.tsx`

- `lib/skin-buy.ts`, order page `components/order/SkinTradeCard.tsx` + `lib/skin-trade.ts`.

Images: rows keep ByMykel's Steam URL; the API rewrites the host to
`cs2_skins_image_host` on the way out (the Akamai host did not open from Uzbekistan,
2026-09-28) and the web asks for `/256fx256f` on cards, `/512fx384f` on the item page.

## Public interface

```python
from yupay.modules.skins.api import (
    DEFAULT_RULES,     # the seed pricing document
    PricingRules,      # validated pricing document (brackets, liquidity, pp maps, floor…)
    Quote,             # a sell price with every component that made it
    SkinItem,          # ORM: one item at one wear (+ Doppler phase)
    SkinPricingRules,  # ORM: row 1, the pricing document as JSONB
    SkinSearchAlias,   # ORM: alias -> text for search
    admin_router,      # /api/v1/admin/skins/*
    import_catalog,    # the daily ByMykel import (scheduler)
    load_rules,        # Redis -> row 1 -> DEFAULT_RULES
    quote,             # cost units -> Quote
    router,            # /api/v1/skins/*
    sync_prices,       # the five-minute snapshot fold (scheduler)
)
```

`/skins/facets?category=<slug>` scopes weapons, wears and rarities to one category
(categories stay global for the tile row); rarities carry their colour. Weapons lead with
`service.WEAPON_PRIORITY` (AK-47, M4A4, M4A1-S, AWP, …), then by count.

## Stored prices

`sell_price_usd` and `discount_percent` are derived by `repricing.reprice_rows` after
every price tick, rules `PUT` and item `PATCH`. Each of those three writers takes
`repricing.lock_pricing` (a transaction-scoped advisory lock) first and reads the
rules with `load_rules(db, fresh=True)`, so a tick never prices from rules an admin is
replacing — Redis gets the new document only after the admin's commit.

## Jobs

| Job                    | Interval                              | Gate                                         |
| ---------------------- | ------------------------------------- | -------------------------------------------- |
| `skins_catalog_import` | `SKINS_IMPORT_INTERVAL_HOURS` (24)    | `CS2_SKINS_SYNC_ENABLED`                     |
| `skins_price_sync`     | `SKINS_SNAPSHOT_INTERVAL_MINUTES` (5) | `CS2_SKINS_SYNC_ENABLED` + `WAXPEER_API_KEY` |

## Redis keys

`skins:catalog:ver`, `skins:catalog:{ver}:{sha1}`, `skins:facets:{ver}:{sha1}`,
`skins:suggest:{ver}:{sha1}`, `skins:listings:{slug}`, `skins:listings:{slug}:stale`,
`skins:pricing`, `skins:wax:budget:{minute}`, `skins:wax:breaker` — TTLs and invalidation
in `docs/architecture/cache-keys.md`.

## Test fixtures

`apps/api/tests/fixtures/skins/`: `bymykel_skins.json` and `bymykel_agents.json` (trimmed
ByMykel entries), `snapshot.csv` (the documented CSV snapshot columns), `prices.json`
(`/v1/prices?minified=0`) and `search_v2.json` (`/v2/search-items-by-name` with
`delivery_details=1`, including the undocumented `auto`/`delivery`/`inspect` fields) — all
shapes recorded from the live API on 2026-09-28.

See also: `docs/runbooks/skins-catalog.md`,
`docs/architecture/sequence-diagrams/skins-catalog-sync.mmd`.

## Purchase (plan 3a)

`checkout.price_skin_line` prices a `cs2-skin` order line from the live listing the customer
picked; `tradelink.py` parses, checks (`POST /skins/tradelink/check`) and saves trade links;
`trade_view.skin_trade_out` is the buyer's view of a trade on the order API. Buying and
tracking live in `fulfillment/suppliers/waxpeer_skins.py` and `fulfillment/skin_sweeps.py`;
the automatic refund in `payments.service.refund_order_to_wallet`. Flow:
`docs/product/flows/skins-buy.md`; runbook: `docs/runbooks/skins-purchase.md`.
