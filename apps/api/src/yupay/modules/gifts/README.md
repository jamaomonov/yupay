# `gifts` module

Steam gift packages (region-priced game/Steam-wallet gifts, fulfilled via the
G-Engine gifts endpoints — see `integrations.adapters.gengine`, added in
Task 1 of the Steam Gifts plan).

This task (Task 2) lays the skeleton only: the admin-editable margin
setting, config, and the widened `sku_supplier_mapping.kind` CHECK. Catalog
browsing, pricing, and checkout land in later tasks (3, 4, 7).

## Responsibilities (this task)

- Own the one admin-editable setting for the feature: `margin_percent`,
  applied on top of supplier cost when later tasks price a gift package.
- Serve it to the admin UI (`GET /admin/gifts/settings`) and let an admin
  change it (`PATCH /admin/gifts/settings`).
- Widen `sku_supplier_mapping.kind` to accept `'gift'` alongside the
  existing `'voucher'` / `'game'`, so a Steam gift SKU can be mapped to its
  G-Engine supplier product the same way any other SKU is.

## Public interface

```python
from yupay.modules.gifts.api import (
    STEAM_GIFT_SKU_CODE,       # "steam-gift" — the product-line SKU code
    SteamGiftSettings,         # ORM row (table steam_gift_settings)
    GiftsAdminSettingsOut,     # admin GET/PATCH response shape
    GiftsSettingsIn,           # admin PATCH body
    admin_router,              # /api/v1/admin/gifts/*
    load_margin_percent,       # Redis -> DB row -> env default
    save_margin_percent,       # DB-only upsert of row 1
    publish_margin,            # push a committed margin into Redis
    offered_zones,             # parsed settings.steam_gifts_regions
    default_zone,              # parsed settings.steam_gifts_region_default
)
```

## Cache

| Redis key      | TTL    | Set by                                       |
| --------------- | ------ | --------------------------------------------- |
| `gifts:margin`  | 1 h    | `load_margin_percent` on a DB hit, or `publish_margin` after an admin save |

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

| Method  | Path                      | Returns                                                |
| ------- | ------------------------- | ------------------------------------------------------- |
| `GET`   | `/api/v1/admin/gifts/settings` | `GiftsAdminSettingsOut` — margin, enabled flag, regions |
| `PATCH` | `/api/v1/admin/gifts/settings` | Same, after setting `margin_percent`                    |

Both require `require_admin`. `PATCH` accepts an `Idempotency-Key` header;
a repeated key replays the first response instead of re-running the write.

## Config

| Env var                       | Default        | Meaning                                                        |
| ------------------------------ | -------------- | --------------------------------------------------------------- |
| `STEAM_GIFTS_ENABLED`          | `false`        | Feature flag the public/miniapp routers (Task 3) gate on        |
| `STEAM_GIFTS_MARGIN_PERCENT`   | `10`           | Seeds `steam_gift_settings` row 1 on first read only            |
| `STEAM_GIFTS_REGION_DEFAULT`   | `CIS`          | Default zone, parsed via `default_zone`                         |
| `STEAM_GIFTS_REGIONS`          | `CIS,RU,KZ,UA` | CSV of offered zones, parsed via `offered_zones`                 |

## Tests

- `apps/api/tests/unit/test_gifts_settings.py` — CSV zone parsing;
  Redis -> DB -> env-default precedence of `load_margin_percent`
  (`fakeredis`, no DB).
- `apps/api/tests/integration/test_gifts_admin_settings.py` — admin
  GET/PATCH over HTTP, idempotency replay, 403 for a non-admin.

## What's deliberately **not** here yet

- Catalog browsing, package pricing, and checkout routes (`router`) — Task 3.
- The G-Engine gifts fulfiller wiring — later tasks.
