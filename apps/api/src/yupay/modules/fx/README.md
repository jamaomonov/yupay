# `fx` module

USD-base currency conversion for YuPay's storefront and checkout.

## Responsibilities

- Maintain fresh FX rates for the supported quote currencies (RUB, UZS, USDT).
- Serve a public read endpoint for the storefront.
- Freeze a rate per order at checkout (`fx_snapshots`).
- Tolerate provider outages gracefully via a stale Redis cache.
- Let an admin pin a typed rate per quote (`fx_quote_settings`); when the
  toggle is on, `FxService.get_rate` returns that number with `source=manual`.

## Public interface

```python
from yupay.modules.fx.api import (
    FxService,                # the orchestrator
    build_default_service,    # factory wired to settings + Redis
    FxSnapshot,               # ORM row referenced by orders
    Quote,                    # in-memory result
    ConversionResult,
    FxUnavailableError,
    router,                   # GET /api/v1/fx/rates
)
```

## Provider chain

See [ADR-0008](../../../../../docs/decisions/0008-fx-provider-chain.md) and
[ADR-0057](../../../../../docs/decisions/0057-admin-fx-provider-chain.md).
Default seed (admin can reorder):

1. `fxratesapi.com` — fiat, keyed (`FX_RATES_API_KEY`)
2. `exchangerate-api.com` — fiat, keyed (`FX_EXCHANGERATE_API_KEY`)
3. `exchangerate.host` — fiat, no key
4. `openexchangerates.org` — fiat, keyed
5. `coingecko` — USDT / crypto only

Each provider implements :class:`FxProvider`. Empty keys make `supports` false
so the chain skips that adapter.

## Cache

| Redis key                      | TTL                        | Set by                             |
| ------------------------------ | -------------------------- | ---------------------------------- |
| `fx:rate:{base}:{quote}`       | 15 min                     | Every successful provider call     |
| `fx:rate:{base}:{quote}:stale` | 24 h                       | Same as above (parallel write)     |
| `fx:manual:{quote}`            | none (60 s if row missing) | Admin save, or first Postgres load |
| `fx:provider_chain`            | none                       | Admin save, or first Postgres load |
| `fx:failover:{base}:{quote}`   | none                       | Cleared when the primary answers   |

The scheduled job `fx_refresh` (`apps/scheduler/.../jobs/fx_refresh.py`) walks
the matrix every `FX_REFRESH_INTERVAL_MINUTES` (default 5) so demand reads
mostly hit Redis, writes `fx_rates` history, and runs the 6% drop tripwire
(ADR-0056).

### `override_cache` — memoizing the manual-override read

`get_rate` / `convert` take an optional `override_cache: dict[str, ManualOverride | None]`.
Passed, the `fx:manual:{quote}` lookup is read once per quote and reused for
every later call sharing that same dict; omitted (the default), every call
reads independently, unchanged from before. A caller converting several
amounts in one request — the catalog module resolving N SKUs on one product
page — should open one dict and pass it to every `convert` call, the same
pattern the catalog's own `rate_cache` already used for the guarded market
rate. Without it, a 35-SKU product page re-read one invariant Redis key once
per SKU (`fx:manual:UZS` × 3 inside 50ms on one real request) — wasted round
trips, and more chances to land on a Redis blip than the page needed.

## Tables owned

- `fx_rates` — append-only history of fetched rates.
- `fx_snapshots` — immutable per-order locked rates. Referenced by `orders.fx_snapshot_id`
  once that module lands.
- `fx_quote_settings` — per-quote `use_manual` + `manual_rate` (ADR-0055).
- `fx_provider_settings` — adapter order and enable flags (ADR-0057).

## HTTP surface

| Method  | Path                             | Returns                                                        |
| ------- | -------------------------------- | -------------------------------------------------------------- |
| `GET`   | `/api/v1/fx/rates`               | `RatesOut` — **effective** rate (manual when the toggle is on) |
| `GET`   | `/api/v1/admin/fx/rates`         | `AdminRatesOut` — effective + live FX + toggle                 |
| `POST`  | `/api/v1/admin/fx/refresh`       | Same as admin GET after busting the provider cache             |
| `PATCH` | `/api/v1/admin/fx/rates/{quote}` | `AdminRateOut` — set `use_manual` and optional `manual_rate`   |
| `GET`   | `/api/v1/admin/fx/providers`     | `ProviderChainOut` — live quote per adapter + order            |
| `PUT`   | `/api/v1/admin/fx/providers`     | Same, after replacing the chain                                |

## Tests

- `apps/api/tests/unit/test_fx_service.py` — orchestrator (cache, chain, stale, identity,
  manual override).
- `apps/api/tests/unit/test_fx_providers.py` — each provider with `respx` HTTP mocks.
- `apps/api/tests/integration/test_fx_routes.py` — HTTP endpoint with stubbed chain +
  `fakeredis`.
- `apps/api/tests/integration/test_fx_manual_routes.py` — admin toggle vs public rates.

## Drop tripwire (ADR-0056)

If USD→UZS or USD→RUB **falls** more than `FX_DROP_TRIPWIRE_PCT` (default 6)
versus the last `fx_rates` row, every _active_ payment provider including
wallet goes to `maintenance` and ops get a Telegram alert. Recovery is
manual. USDT is not watched. A rise is ignored. The first tick (empty
history) does not trip.

## What's deliberately **not** here yet

- **Circuit breaker / retry wiring.** Provider adapters report failure cleanly today;
  `tenacity` + `purgatory` middleware will be plugged in once we see real
  flake patterns in staging.
- **Multi-base support.** Internal pricing is USD-only by design (ADR-0004 ledger).
