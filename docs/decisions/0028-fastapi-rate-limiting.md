# 0028. Global FastAPI rate limiting via slowapi with per-process memory storage

- **Status**: Accepted
- **Date**: 2026-06-11
- **Deciders**: core team
- **Tags**: backend | security

## Context and problem statement

AGENTS.md §9 mandates rate limiting on every public endpoint at both Caddy and
FastAPI. Neither layer was actually wired: the Caddyfile documents why the
Caddy `rate_limit` directive is skipped (community module, custom image), and
`slowapi` sat in `pyproject.toml` with no `Limiter` ever constructed. The only
real throttle was the Redis-backed `ip_guard` on auth endpoints.

## Decision drivers

- "Async everywhere on the request path" (AGENTS.md §6): no sync I/O per request.
- Single-VPS deployment with a handful of uvicorn workers.
- An outer circuit breaker is needed for every route, not just auth.

## Considered options

1. **slowapi + per-process `memory://` storage** — zero I/O, limit counted per
   worker (N workers ⇒ up to N× the nominal limit).
2. **slowapi + Redis storage** — exact global counts, but `limits`' Redis
   backend is synchronous and blocks the event loop on every request.
3. **Custom async middleware on redis.asyncio** — exact and async, but bespoke
   sliding-window code on the hot path that we then own forever.

## Decision outcome

**Chosen option:** Option 1, because the limiter is an outer circuit breaker,
not a billing-grade counter — a small multiple of the nominal limit is fine,
while blocking the event loop (option 2) or owning custom throttling code
(option 3) is not. Sensitive endpoints keep their precise Redis-backed
`ip_guard` on top.

Wiring: `Limiter(key_func=first X-Forwarded-For entry, default_limits=[settings.rate_limit_default],
storage_uri="memory://", headers_enabled=True, key_style="endpoint")` +
`SlowAPIMiddleware`; 429 via slowapi's handler. Off under `ENVIRONMENT=test`
unless `RATE_LIMIT_ENABLED=true` (the suite would trip it).

### Amended 2026-08-26, before the first paid-traffic campaign

Three things this ADR assumed turned out not to hold in the implementation.

**`key_style="endpoint"` is now explicit.** slowapi's default is `"url"`, which
buckets by the exact path — so `/orders/aaa` and `/orders/bbb` each got their
own 120/minute. Every route carrying a path parameter was therefore effectively
unlimited, and the whole ceiling fell on the fixed-path endpoints every session
touches. The "per-IP ceiling on every route" claimed below simply did not exist
for the majority of routes. It also made key cardinality `IPs × distinct URLs`,
and `limits`' MemoryStorage sweeps every live key on a timer — so a surge
inflated the limiter into a load source of its own.

**CORS now wraps the limiter.** `add_middleware` prepends, so the last
registration is outermost; `SlowAPIMiddleware` was registered after CORS and
therefore sat outside it. Since the limiter short-circuits, its 429 never
passed through the CORS layer, the browser blocked it, and `fetch` rejected as
a network error — indistinguishable from an outage, so the clients' default
retry fired three more times. The limiter was multiplying the traffic it
existed to shed.

**Provider callbacks are exempt.** Only `/healthz` and `/readyz` were. A 429 to
an acquirer or a supplier costs money and buys nothing: G2B fires each callback
once with a single retry, so a throttled one loses the delivery notification
for good, and Payme reads a 429 as a transport failure and retries into it.
Every one of these routes authenticates its caller itself. The exempt list
lives in `bootstrap._exempt_provider_callbacks` so it can be audited in one
place.

### Positive consequences

- Every route gets a per-IP ceiling (`RATE_LIMIT_DEFAULT`, default 120/minute),
  bucketed per route rather than per URL.
- No new infra dependency on the request path; no event-loop blocking.

### Negative consequences

- The effective limit scales with worker count; the Caddy-layer limit from
  AGENTS.md §9 is still pending (needs a custom Caddy build or Cloudflare).
- Counters reset on process restart.

## Validation

`tests/integration/test_rate_limit.py`: a 3/minute app returns 429 on the 4th
request, health probes stay exempt, and the default test app is unthrottled.
`tests/integration/test_rate_limiter_shape.py` covers the three amendments: two
URLs of one route share a budget, a 429 carries the CORS header, and no
provider callback is ever throttled.
Revisit if the deploy moves beyond a single VPS — switch to `limits`' async
Redis storage once slowapi supports it on the middleware path.
