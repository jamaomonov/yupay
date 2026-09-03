# `gifts` module

Steam gift packages (region-priced game/Steam-wallet gifts, fulfilled via the
G-Engine gifts endpoints — see `integrations.adapters.gengine`, added in
Task 1 of the Steam Gifts plan).

Task 2 laid the skeleton: the admin-editable margin setting, config, and the
widened `sku_supplier_mapping.kind` CHECK. Task 3 (this one) adds the live
catalog proxy — listing, hot offers, app detail, and per-app DLC, all read
through a stale-while-error Redis cache in front of G-Engine. Checkout lands
in a later task (7).

## Responsibilities

- Own the one admin-editable setting for the feature: `margin_percent`,
  applied on top of supplier cost when pricing a gift package (Task 2).
- Serve it to the admin UI (`GET /admin/gifts/settings`) and let an admin
  change it (`PATCH /admin/gifts/settings`).
- Widen `sku_supplier_mapping.kind` to accept `'gift'` alongside the
  existing `'voucher'` / `'game'`, so a Steam gift SKU can be mapped to its
  G-Engine supplier product the same way any other SKU is.
- Proxy G-Engine's gifts catalog for browsing: paged listing (with search),
  a curated hot-offers list, one app's full detail (packages priced per
  offered zone), and that app's DLC, filtered/paged server-side (Task 3).
  Every route 404s while `steam_gifts_enabled` is off.

## Public interface

```python
from yupay.modules.gifts.api import (
    STEAM_GIFT_SKU_CODE,       # "steam-gift" — the product-line SKU code
    SteamGiftSettings,         # ORM row (table steam_gift_settings)
    GiftsAdminSettingsOut,     # admin GET/PATCH response shape
    GiftsSettingsIn,           # admin PATCH body
    GiftAppOut,                # public catalog row DTO
    GiftAppDetailOut,          # public app detail DTO
    GiftPackageOut,            # public per-package pricing DTO
    GiftZonePriceOut,          # public per-zone price DTO
    GiftsListOut,              # public paged-list envelope
    admin_router,              # /api/v1/admin/gifts/*
    router,                    # /api/v1/gifts/* (public catalog browsing)
    load_margin_percent,       # Redis -> DB row -> env default
    save_margin_percent,       # DB-only upsert of row 1
    publish_margin,            # push a committed margin into Redis
    offered_zones,             # parsed settings.steam_gifts_regions
    default_zone,              # parsed settings.steam_gifts_region_default
)
```

`gifts.service` (not re-exported through `api.py` — internal to the module,
consumed directly by `gifts.routes` and by later tasks per the plan) adds:

```python
from yupay.modules.gifts.service import (
    sell_price_usd,   # supplier USD cost -> our 2dp sell price (margin applied)
    zone_price_usd,   # package["prices"] -> wholesale USD for one zone, or None
    list_apps,        # cached page of the raw upstream catalog listing
    get_app,           # cached full app detail; NotFoundError on an upstream 404
    hot_offers,        # cached, capped-at-12 pinned + best-discount list
)
```

## Cache

| Redis key                                                        | TTL    | Set by                                                                     |
| ---------------------------------------------------------------- | ------ | -------------------------------------------------------------------------- |
| `gifts:margin`                                                   | 1 h    | `load_margin_percent` on a DB hit, or `publish_margin` after an admin save |
| `gifts:list:{offset}:{limit}` (+ `:stale`, 24 h)                 | 1 h    | `gifts.service.list_apps` — default (no-search) listing page               |
| `gifts:search:{sha1(query)}:{offset}:{limit}` (+ `:stale`, 24 h) | 15 min | `gifts.service.list_apps` — a searched listing page                        |
| `gifts:detail:{app_id}` (+ `:stale`, 24 h)                       | 15 min | `gifts.service.get_app`                                                    |
| `gifts:hot` (+ `:stale`, 24 h)                                   | 1 h    | `gifts.service.hot_offers`                                                 |

Every fresh key above has a `:stale` twin, written at the same time, that
outlives it by a full day. `gifts.service._cached_json` is the one helper
behind all four: fresh Redis entry, then upstream, then the stale twin on a
G-Engine failure (`GEngineError` / `GEngineUnavailableError`), then
`UpstreamUnavailableError` (502) only when neither exists. A Redis error
itself is swallowed at every step — a cache outage degrades to "always hit
upstream," never a 500. See `docs/architecture/cache-keys.md` for the full,
authoritative row-by-row listing.

## Commit-then-publish invariant

`save_margin_percent` only ever touches Postgres (`flush()`, no cache
write). The admin route commits that write, and only **after** the commit
succeeds does it call `publish_margin` to push the new value into Redis —
identical ordering to `fx.quote_settings.upsert_override` /
`fx.routes.admin_set_rate`. Publishing before the commit would make an
uncommitted margin briefly "live" in Redis; if the commit (or anything after
it, such as the idempotency-replay write) then failed, Postgres would roll
back while Redis kept serving a value no row supports, with nothing to
expire it and the admin page — which reads the toggle from Postgres —
showing no sign of the divergence.

## Tables owned

- `steam_gift_settings` — singleton row (`id` pinned to `1` by a CHECK):
  `margin_percent`, `updated_by`, `updated_at`.

## HTTP surface

| Method  | Path                                 | Returns                                                    |
| ------- | ------------------------------------ | ---------------------------------------------------------- |
| `GET`   | `/api/v1/admin/gifts/settings`       | `GiftsAdminSettingsOut` — margin, enabled flag, regions    |
| `PATCH` | `/api/v1/admin/gifts/settings`       | Same, after setting `margin_percent`                       |
| `GET`   | `/api/v1/gifts/catalog`              | `GiftsListOut` — paged listing, `?search=&limit=&offset=`  |
| `GET`   | `/api/v1/gifts/catalog/hot`          | `GiftsListOut` — up to 12 pinned/discounted apps           |
| `GET`   | `/api/v1/gifts/catalog/{app_id}`     | `GiftAppDetailOut` — packages priced per offered zone      |
| `GET`   | `/api/v1/gifts/catalog/{app_id}/dlc` | `GiftsListOut` — that app's DLC, `?search=&limit=&offset=` |

The admin pair requires `require_admin`; `PATCH` accepts an
`Idempotency-Key` header and a repeated key replays the first response
instead of re-running the write. The public `/gifts/*` routes require no
auth but all 404 (`NotFoundError`) while `steam_gifts_enabled` is false —
enforced once, as a router-level dependency, so a route added later inherits
the guard automatically. No per-route rate-limit bucket, same as
`catalog/routes.py` — the app-wide slowapi defaults apply.

Money on every public DTO is a `str`, not a `Decimal`: `price_usd` is our
2dp sell price after margin, `price_uzs` is a whole-UZS display string that
is `None` whenever FX was unavailable for that request (the page still
renders — it just has nothing to show under the "≈ N UZS" line). The UZS
rate is fetched once per request (`FxService.convert("1", base="USD",
quote="UZS")`) and multiplied per row, never re-fetched per item.

## Config

| Env var                      | Default        | Meaning                                                                                                                       |
| ---------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `STEAM_GIFTS_ENABLED`        | `false`        | Feature flag the public/miniapp routers (Task 3) gate on                                                                      |
| `STEAM_GIFTS_MARGIN_PERCENT` | `10`           | Seeds `steam_gift_settings` row 1 on first read only                                                                          |
| `STEAM_GIFTS_REGION_DEFAULT` | `UZ`           | Default _country_ (a legacy zone label such as `CIS` is still tolerated and resolved to a country), parsed via `default_zone` |
| `STEAM_GIFTS_REGIONS`        | `CIS,RU,KZ,UA` | CSV of offered zones, parsed via `offered_zones`                                                                              |

## Tests

- `apps/api/tests/unit/test_gifts_settings.py` — CSV zone parsing;
  Redis -> DB -> env-default precedence of `load_margin_percent`
  (`fakeredis`, no DB).
- `apps/api/tests/integration/test_gifts_admin_settings.py` — admin
  GET/PATCH over HTTP, idempotency replay, 403 for a non-admin.
- `apps/api/tests/unit/test_gifts_service.py` — `sell_price_usd` /
  `zone_price_usd` pricing math; `_cached_json`'s fresh/miss/stale/
  raise-with-no-stale branches (`fakeredis`, a stubbed `fetch`); `hot_offers`'
  discount filter + sort + 12-item cap (a stubbed G-Engine client).
- `apps/api/tests/integration/test_gifts_catalog_routes.py` — the enabled
  guard 404s every route while off; listing maps fields and applies margin;
  detail narrows package prices to the offered zones; `/dlc` filters and
  pages the cached detail server-side, never the flat listing; a G-Engine
  outage serves the warm stale cache, and 502s when there is none
  (`respx`-mocked upstream, a manual FX override in place of a live rate).

## What's deliberately **not** here yet

- Checkout routes — Task 7.
- Fulfilment wiring — a later task.
- `_PINNED_APP_IDS` (curated hot-offer apps) is an empty tuple: spec §4.2
  wants it admin-editable, not yet built.
