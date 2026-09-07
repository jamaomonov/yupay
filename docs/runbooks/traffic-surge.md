# Runbook: a traffic surge

Written before the first paid campaign (August 2026), when measured customer
load was **0.019 req/s** on the busiest endpoint and the design target was 200.
The box was idle; what limits throughput is software, not hardware.

## The ceilings, measured on prod

| Ceiling                            | Why                                                                                             | Status           |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- | ---------------- |
| **~10 req/s** whole API            | argon2 takes 98 ms per password check and blocks the single event loop                          | open — see below |
| **~17 req/s** on `/catalog/brands` | 58 ms CPU, 14 SQL queries for 18 brands (model-level `lazy="selectin"` drags the whole catalog) | open             |
| **20 connections**                 | the DB pool, held across supplier HTTP calls                                                    | open             |

One uvicorn process means one event loop on one of eight cores. Any CPU an
endpoint burns is a ceiling for the _whole_ API, not for that route.

## First checks when the site is slow

Our Prometheus is internal-only. Port 9090 on the host belongs to the
**neighbour stack** — querying it returns their traffic, not ours.

```
ssh ubuntu@<host>
docker exec yupay-prod-prometheus-1 wget -qO- \
  'http://localhost:9090/api/v1/query?query=<urlencoded>'
```

In order:

1. **CPU of the API process.** With one worker this is the saturation signal and
   it leads every symptom by minutes.
   `rate(process_cpu_seconds_total{job="api"}[5m])` — above 0.85 means the loop
   is full.
2. **File descriptors.** `process_open_fds{job="api"} / process_max_fds{job="api"}`.
   Past ~0.7 you are approaching a hard wall: at the limit uvicorn stops
   accepting _every_ connection, HTTP included, and does not recover on its own.
3. **DB connections.** `sum(pg_stat_database_numbackends)` against
   `max_connections`. Saturation here surfaces as 500s on every surface at once,
   because the pool is shared by the whole process.
4. **429 rate.** A spike means our own limiter is shedding real customers —
   check which bucket before raising anything.

Note the latency histogram cannot see past one second: buckets are
`0.1 / 0.5 / 1.0 / +Inf`, so a p95 of "1000 ms" means "somewhere above a
second, unmeasurable". Do not size anything on it.

## Rate limits, and which one is biting

There are two independent mechanisms. Both answer 429, and telling them apart
is the first thing to do.

**The global limiter** (`bootstrap._build_limiter`) is in-process memory,
`RATE_LIMIT_DEFAULT` per IP, bucketed **per route** (`key_style="endpoint"`).
Every acquirer and supplier callback is exempt, and so is every
`/merchant/v1` route — see `bootstrap._exempt_self_authenticating_routes`, and
do not remove an entry without reading ADR-0028's amendment: a 429 to G2B
loses a delivery notification for good, and a coarse-tier 429 to a merchant is
a non-RFC-7807 body on a published third-party contract. **A merchant
complaining of 429s is therefore never this limiter** — it is the Redis
`ip_guard` below (bucket `merchant-api`) or the per-key counter
(`merchants:apikey:{key_id}`); both answer problem+json with `Retry-After`.

**The ip guard** (`modules/auth/ip_guard.py`) is Redis-backed and throttles on
two axes:

- per IP, per bucket — `auth:ipguard:{bucket}:{ip}`, sized for a mobile-carrier
  NAT (many real subscribers share one address);
- per identity — `auth:ipguard:{bucket}:{ip}:s:{sha256(email)[:32]}`, tight,
  `AUTH_IP_GUARD_SUBJECT_MAX`. This is the axis that blunts brute force.

To see whether a specific address is being throttled:

```
docker exec yupay-prod-redis-1 redis-cli -a "$REDIS_PASSWORD" \
  --scan --pattern 'auth:ipguard:*:<ip>*'
```

To loosen one bucket without touching the others, set
`AUTH_IP_GUARD_BUCKET_MAX` in `secrets/api.env` and `up -d api`. Values `<= 0`
are ignored, so a typo falls back to the default rather than disabling the
guard. **Do not** raise `AUTH_IP_GUARD_SUBJECT_MAX` to fix a lockout complaint —
that is the brute-force control; raise the IP bucket instead.

## Redis is full

`maxmemory` is 512 MB and the policy is **`noeviction` on purpose**: Redis no
longer holds a work queue (the fulfilment saga moved to a Postgres-native
queue, ADR-0064) — it holds `ip_guard`/rate-limit counters, the `fx`/catalog/
inventory/stats caches (see `docs/architecture/cache-keys.md`), and the
`realtime` pub/sub channel. Evicting any of those to make room is still
wrong: it would silently weaken rate limiting or drop a cached value or a
live pub/sub message a customer is relying on this second. Writes failing
is the correct behaviour.

If it fills, check `docs/architecture/cache-keys.md` for which key has no
TTL or a long one, and `redis-cli --bigkeys` / `MEMORY USAGE` for which
prefix is actually large, before raising the ceiling — the container's
`mem_limit` (768m) is deliberately higher so Redis refuses writes before the
OOM killer sees it.

## Memory pressure on the host

The VPS is shared with an unrelated production stack and **has no swap**, so
pressure goes straight to the OOM killer, which picks by size rather than by
owner. Every container now declares a `mem_limit` — a test asserts it, so a new
service cannot quietly arrive without one.

If a container is being killed (exit 137), resist tightening its neighbours:
check what actually grew. A too-tight limit produces a crash loop under
`restart: unless-stopped`, and for postgres that means repeated crash recovery
and a hard outage.

## What degrades on its own, and what does not

- **Player check** — advisory, circuit-broken (ADR-0059). During a G2B outage it
  answers "couldn't check" in ~150 ms instead of ~15 s. Nothing to do.
- **FX rates** — on the checkout path. If the whole provider chain fails,
  customers **cannot buy**. There is no single-flight lock, so a cache miss
  under load means every concurrent request calls the provider.
- **Fulfilment** — still runs inline in the request transaction (the ADR-0013
  follow-through is open), so a slow supplier consumes DB connections directly.
  This is the mechanism behind most "everything is 500ing" incidents.
- **Storefront HTML** — prerendered at build and served from the Cloudflare
  edge. See ADR-0060; the health check is `cf-cache-status` on a brand page,
  which should read `HIT`. `BYPASS` means a rule matched but something on the
  response blocks caching (a `Set-Cookie` is the usual culprit); `DYNAMIC`
  means no cache rule matched at all.

## Deploys during a campaign

Deploys are stop-start, not rolling: expect 5–15 seconds of 502s. Migrations run
_before_ the new version comes up, so the old code briefly serves against the
new schema. Schedule outside campaign hours and tell the agency the window.

## Cloudflare, and what is configured there

None of this lives in the repo — it is zone configuration. Recorded here so an
incident does not start with archaeology.

**Cache rules** (zone `yupay.uz`, phase `http_request_cache_settings`), in order:

1. `cdn.yupay.uz` — one year, override origin. R2 media, ULID-named and never
   mutated.
2. `/_next/image` — cache eligible, edge TTL from origin. The query string
   stays in the key: `url`/`w`/`q` select the variant.
3. Storefront HTML — `/`, `/store*`, `/legal*` and their `/en` and `/uz`
   prefixes. Cache eligible, edge TTL from origin, and the **cache key excludes
   the query string entirely**. That exclusion is load-bearing: ad traffic
   arrives as `?utm_source=…&fbclid=…`, and with the default key every click
   would be a unique entry and a miss.

Nothing user-specific is in that set. `/account/*`, `/checkout/*` and
`/orders/*` are excluded, and the storefront pages read no cookies or headers
during server rendering — auth state lives in localStorage.

**Rate limiting** (phase `http_ratelimit`): one rule, 20 requests / 10s per IP,
on `login`, `register`, `password/reset` and `admin-dev` only. The Free plan
allows exactly one rule, a 10s window and a 10s block, so those numbers are the
plan's rather than a judgement. `/refresh` and `/me` are deliberately not
matched — they fire during ordinary browsing, and throttling them would break
signed-in visitors behind a carrier NAT.

A blocked request gets Cloudflare's own response, which carries no CORS header
— so the browser reports a network error rather than a 429. That is tolerable
at this threshold (real login volume is a few per hour) but it is the reason
the threshold is generous.

## Alerting

Alerts go to the ops Telegram chat — the same one the bot posts fulfilment
failures to. That is deliberate: a channel nobody has open is the failure mode
alerting is supposed to remove, not reproduce.

Alertmanager renders its config at start-up from
`infra/alertmanager/alertmanager.tmpl.yml`, substituting `ALERT_BOT_TOKEN` and
`ALERT_CHAT_ID` from `secrets/alertmanager.env`. Both come from `api.env`:
`TG_ALERT_BOT_TOKEN` and `TG_ALERT_CHAT_ID`. It must be that token and not the
storefront or admin bot — ops alerts run on their own bot deliberately, and it
is the one that is actually a member of the alert chat. Another bot's token
authenticates fine and then fails to post, which looks exactly like no alerts. Alertmanager performs no environment expansion of its own, so a
`${VAR}` written directly into the config would load, validate, and then
authenticate to Telegram as the literal string — every alert silently lost. A
test guards that.

**If alerts stop arriving**, check in this order:

1. `curl -s localhost:9090/api/v1/alertmanagers` inside the prometheus
   container — an empty `activeAlertmanagers` means Prometheus is not wired to
   it at all, which was the state until August 2026.
2. `docker logs yupay-prod-alertmanager-1` — a bad token shows as a Telegram
   API rejection here and nowhere else.
3. `docker exec yupay-prod-alertmanager-1 cat /alertmanager/alertmanager.yml` —
   if it still contains `__ALERT_BOT_TOKEN__`, the entrypoint substitution did
   not run.

**Repeat intervals are long on purpose** — 4h, and 1h for `page`. This chat also
carries fulfilment failures, and an alert that repeats every few minutes trains
people to mute the chat, which is how a real incident gets missed.

**Two alerts inhibit others**: `ApiDown` suppresses the API's saturation,
latency, error-rate and descriptor alerts, and `PostgresDown` suppresses the
connection-count alert. Those are consequences, not information.

**There is no queue-depth alert.** The old one watched `redis_list_length`,
which nothing emits — the exporter only reports it for keys listed in
`REDIS_EXPORTER_CHECK_KEYS`, and Dramatiq never stored queues as plain lists
anyway, so no configuration could have made it fire. The fulfilment queue is
`fulfillment_tasks` in Postgres now (ADR-0064) — depth is checked manually
via the SQL in `docs/runbooks/fulfillment-queue.md`. An automated alert on
pending-row age/count is a real follow-up candidate, not built yet.
