# 0008. FX provider chain

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, money, integrations

## Context

YuPay prices internally in **USD** (see ADR-0004 ledger model). The storefront and the
checkout charge customers in their local currency (RUB, UZS, or USDT at MVP). For that we
need accurate, fresh USD → quote exchange rates and a way to **freeze** the rate at
checkout so a customer pays what they saw on the product page even if the market moves.

Constraints:

- No vendor lock-in — we will trade providers as their pricing / reliability change.
- Free tier first (no contracts on day one), but the abstraction must accept commercial
  providers later.
- USDT is special — fiat FX APIs don't price stablecoins consistently.
- A single failed provider must not break the storefront. Stale rates with a known
  upper-bound staleness are acceptable; "no rate at all" is not.

## Decision

### Provider order

| Slot | Provider | Coverage | Notes |
|---|---|---|---|
| primary | **exchangerate.host** | All fiat pairs (USD → RUB, USD → UZS, USD → EUR, ...) | Free, no API key |
| fallback | **openexchangerates.org** | Same fiat coverage | Free key needed; activate when primary degrades |
| stablecoin | **coingecko** (`simple/price`) | USDT/USDC/TON in USD | Free; rate-limited but generous |

`USD → USDT` is always routed to **coingecko**. Everything else is fiat-first; we fall
through to the next provider on failure.

### Pipeline

```
get_rate(base="USD", quote="RUB"):
    1. fresh cache hit?            → return
    2. provider chain → fetch
       2a. primary.get_rate(...)    timeout 1.5s, 1 retry
       2b. on failure → fallback   timeout 1.5s, 1 retry
       2c. on failure → coingecko (only for crypto pairs)
    3. write fresh + stale to Redis
    4. return
```

If **all** providers fail:

- If `:stale` exists, serve it (one log line, no error).
- Otherwise raise `FxUnavailableError` — callers decide whether to surface a 503 on the
  storefront or to allow checkout to proceed without conversion (most pricing is USD
  anyway).

### Caching (Redis)

| Key | TTL | Purpose |
|---|---|---|
| `fx:rate:{base}:{quote}` | 15 min | Hot read path; refreshed by the scheduler every 5 min |
| `fx:rate:{base}:{quote}:stale` | 24 h | Graceful degradation when all providers fail |

A scheduled job (`fx_refresh`) runs every 5 minutes and pushes the matrix of supported
pairs through the chain. Demand reads only ever touch Redis under steady state.

### Checkout snapshot

At order creation we **snapshot** the rate into `fx_snapshots`:

```
fx_snapshots(id, base, quote, rate NUMERIC(20,6), source, fetched_at)
orders.fx_snapshot_id → fx_snapshots(id)
```

The snapshot is immutable. If the snapshot is older than 5 minutes at checkout time we
re-fetch and supersede; the order then references the new row. This prevents a customer
holding the cart open for hours and exploiting an outdated quote.

### Resilience

- HTTP via **httpx** (timeout 1.5 s per call).
- Retries via **tenacity** — 1 retry with exponential backoff (200 ms → 600 ms) on
  network errors / 5xx / 429 only.
- Circuit breaker via **purgatory** — 5 consecutive failures opens the breaker for 60 s.
- Provider responses are validated by Pydantic before they reach the cache. Bad payloads
  are treated as failure and fall through.

### Configuration

Settings keys (added to ``yupay.core.config.Settings``):

- `fx_primary_url` — exchangerate.host endpoint
- `fx_fallback_url` + `fx_fallback_api_key` — openexchangerates
- `fx_crypto_url` — coingecko endpoint
- `fx_cache_fresh_seconds` (default 900)
- `fx_cache_stale_seconds` (default 86_400)
- `fx_provider_timeout_seconds` (default 1.5)
- `fx_supported_quotes` (default `["RUB", "UZS", "USDT"]`)

## Consequences

- A provider change is one new adapter file + a registry edit. No business code moves.
- Storefront never sees "rate missing" under normal conditions — the stale-key safety net
  buys us 24 h of graceful degradation.
- Snapshot semantics make refunds and accounting deterministic (no "what was the rate at
  that moment?" ambiguity).

## Alternatives considered

- **Single provider (no fallback)** — rejected: an outage at the provider would freeze
  checkout. Free providers offer no SLA.
- **Stablecoin-only pricing** (skip fiat conversion) — rejected: most customers think in
  fiat; we cannot demand USDT.
- **Daily refresh** — rejected: 0.5–2 % daily moves on RUB/USD are too large to ignore on
  high-AOV orders.

## References

- [ADR-0004 — double-entry ledger](./0004-double-entry-ledger.md)
- [`docs/architecture/cache-keys.md`](../architecture/cache-keys.md)
- [exchangerate.host](https://exchangerate.host/)
- [openexchangerates.org](https://openexchangerates.org/)
- [CoinGecko `simple/price`](https://www.coingecko.com/en/api/documentation)
