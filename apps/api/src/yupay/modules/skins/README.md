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
