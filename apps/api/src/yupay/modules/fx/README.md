# `fx` module

USD-base currency conversion for YuPay's storefront and checkout.

## Responsibilities

- Maintain fresh FX rates for the supported quote currencies (RUB, UZS, USDT).
- Serve a public read endpoint for the storefront.
- Freeze a rate per order at checkout (`fx_snapshots`).
- Tolerate provider outages gracefully via a stale Redis cache.

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

See [ADR-0008](../../../../../docs/decisions/0008-fx-provider-chain.md). In order:

1. `exchangerate.host` — fiat primary (no key)
2. `openexchangerates.org` — fiat fallback (free key)
3. `coingecko` — stablecoin / crypto

Each provider implements :class:`FxProvider` and is composable with retries and circuit
breakers at the service layer.

## Cache

| Redis key | TTL | Set by |
|---|---|---|
| `fx:rate:{base}:{quote}` | 15 min | Every successful provider call |
| `fx:rate:{base}:{quote}:stale` | 24 h | Same as above (parallel write) |

The scheduled job ``fx_refresh`` (planned, will live in `apps/scheduler`) walks the
matrix every 5 min so demand reads only ever hit Redis under steady state.

## Tables owned

- `fx_rates` — append-only history of fetched rates.
- `fx_snapshots` — immutable per-order locked rates. Referenced by `orders.fx_snapshot_id`
  once that module lands.

## HTTP surface

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/v1/fx/rates` | `RatesOut` — list of `{base, quote, rate, fetched_at, source}` |

## Tests

- `apps/api/tests/unit/test_fx_service.py` — orchestrator (cache, chain, stale, identity).
- `apps/api/tests/unit/test_fx_providers.py` — each provider with `respx` HTTP mocks.
- `apps/api/tests/integration/test_fx_routes.py` — HTTP endpoint with stubbed chain +
  `fakeredis`.

## What's deliberately **not** here yet

- **Scheduled refresh job.** The `apps/scheduler` skeleton exists; the actual
  `fx_refresh` job will land alongside the `orders` module (so we can compose with
  fulfilment timeouts in one PR).
- **Circuit breaker / retry wiring.** Provider adapters report failure cleanly today;
  `tenacity` + `purgatory` middleware will be plugged in once we see real
  flake patterns in staging.
- **Multi-base support.** Internal pricing is USD-only by design (ADR-0004 ledger).
