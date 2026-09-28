# `skins` module

CS2 skins (ADR-0093): our own item catalogue from ByMykel/CSGO-API, Waxpeer's
`auto` listings folded onto it every five minutes, and the read API the
storefront browses. Purchase, fulfilment and tracking are separate plans
(spec §9) and do not exist yet.

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
