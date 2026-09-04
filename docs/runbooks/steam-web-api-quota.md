# Runbook — Steam Web API quota

One Steam Web API key, a **100 000 calls/day ceiling**, and two consumers that
share it:

| Consumer        | What spends it                                                                                                                     | Cost per event                                                                                                          |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `gifts_profile` | `POST /api/v1/gifts/steam-profile` — the pre-purchase recipient check. **Unauthenticated**, rate-limited per IP only (120/min).    | 1 call for a `/profiles/{steamid64}` link, **2** for an `/id/{vanity}` link, 0 on a Redis cache hit or an `s.team` link |
| `auth_signin`   | Steam sign-in's `GetPlayerSummaries` (`fetch_persona`) — the nickname and avatar on the account. OpenID itself costs **no** quota. | 1 call per sign-in                                                                                                      |

Exhausting the key is **not an outage**: recipient checks answer
`unavailable` (non-blocking — the buyer can still pay) and sign-ins go
nameless. That is exactly why it needs watching. Nothing breaks loudly, so
without the counters below a burn was something nobody could explain, and the
only symptom was buyers paying without having seen who the gift goes to.

## The signals

Both counters are exported by the API at `/metrics` (see
`docs/architecture/metrics.md` for the full label vocabulary):

- `yupay_steam_web_api_calls_total{endpoint,consumer,outcome}` — one increment
  per keyed Steam call.
- `yupay_gifts_steam_profile_checks_total{verdict,source}` — one increment per
  answer the recipient check gives.

Grafana: **YuPay → "Steam · Web API quota & recipient checks"**
(`yupay-steam-quota`).

Alerts (both `warn`, both in `infra/prometheus/alerts/api.yml`):

| Alert                           | Fires when                                                                     | Means                                                               |
| ------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| `SteamWebApiBurnRateHigh`       | the current call rate, extrapolated over 24h, exceeds 50% of the 100k key      | something is spending the key faster than customers plausibly could |
| `SteamProfileChecksUnavailable` | >50% of recipient checks answer `unavailable` for 15 min (with a volume floor) | Steam trouble, an exhausted key, or an unset `STEAM_API_KEY`        |

## Queries

Prometheus is internal-only; port 9090 on the host belongs to the **neighbour
stack** (see `traffic-surge.md`). Query ours from inside the container:

```bash
ssh ubuntu@<host>
docker exec yupay-prod-prometheus-1 wget -qO- \
  'http://localhost:9090/api/v1/query?query=<urlencoded>'
```

| Question                           | Query                                                                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How much of today's key is gone?   | `sum(increase(yupay_steam_web_api_calls_total[24h]))`                                                                                                                     |
| Who is spending it?                | `sum by (consumer) (increase(yupay_steam_web_api_calls_total[24h]))`                                                                                                      |
| Is Steam refusing us?              | `sum by (outcome) (rate(yupay_steam_web_api_calls_total[15m]))`                                                                                                           |
| What are buyers being told?        | `sum by (verdict) (rate(yupay_gifts_steam_profile_checks_total[15m]))`                                                                                                    |
| Cache hit rate (the early warning) | `sum(rate(yupay_gifts_steam_profile_checks_total{source="cache"}[1h])) / clamp_min(sum(rate(yupay_gifts_steam_profile_checks_total{source=~"cache\|steam"}[1h])), 0.001)` |

`local` is excluded from the hit-rate denominator on purpose: those requests
(`s.team` friend links, or no API key configured) never consult the cache, so
counting them as misses would make a flood of friend links read as a cache
collapse.

## Reading a spike

**Call rate up, cache hit rate collapsing.** Distinct links are being walked —
each one is a guaranteed miss and one or two calls. This is the signature of
someone pulling the lever, not of more customers: real buyers paste the same
handful of links repeatedly (checkout re-checks), so normal traffic keeps a
healthy hit rate. Expect `verdict=not_found` to rise with it if the links are
made up.

**`not_found` spiking on its own.** Either enumeration (each miss is a Steam
call) or a broken client sending malformed links that still parse. Check
whether it is concentrated in the vanity shape — `sum by (endpoint)` on the
call counter — since `/id/` links cost double.

**`unavailable` spiking.** Steam trouble, an exhausted key, or a missing
`STEAM_API_KEY`. Tell them apart with the call counter: `outcome="error"`
rising means we are calling and Steam is refusing; **no calls at all** while
checks keep answering `unavailable` means the key is unset (verdicts land on
`source="local"`), so check the API container's environment before blaming
Steam.

**Calls up, `consumer="auth_signin"`.** A login storm, not the gift check.
Nothing to do about the quota itself; the gift check will degrade first
because it is the larger consumer.

## What to do

1. **Confirm the shape.** Is it the gift check (`consumer="gifts_profile"`)
   with a collapsed hit rate? Then it is link-walking.
2. **Find the source at the edge, not in our labels.** No metric here carries
   an IP, a link or a steamid — deliberately (see
   `docs/architecture/metrics.md`). The client is identified from Caddy's
   access log in Loki, or from Cloudflare's analytics:
   ```
   {compose_project="yupay-prod",container="caddy"} |= "/api/v1/gifts/steam-profile"
   ```
3. **Tighten the per-IP budget.** The bucket is `gifts-steam-profile`,
   currently **120 per minute per IP** (sized for a carrier NAT, not for one
   person). Lower it via `AUTH_IP_GUARD_BUCKET_MAX` in `secrets/api.env` +
   `up -d api` — see `traffic-surge.md` § "Rate limits" for the exact
   mechanics and for how to check whether one address is already throttled.
4. **Block at Cloudflare** if it is distributed across IPs — the WAF is the
   edge tier for this API (AGENTS.md §9); there is no rate limiting in Caddy.
5. **Turn the feature off as a last resort.** `STEAM_GIFTS_ENABLED=false` on
   the API 404s the whole `/gifts/*` router, recipient check included — it
   also stops the gift catalog, so this trades a feature for the key. Steam
   sign-in keeps working (it does not read that flag) and will still have a
   key to use.
6. **Do not "fix" it by caching `unavailable`.** That verdict is our failure,
   not a fact about the profile; caching it would keep telling the next buyer
   the same lie for six hours. See `apps/api/src/yupay/modules/gifts/profile.py`.

If the key really is exhausted, there is no reset lever on our side — Steam's
quota rolls over on its own. Mitigate demand (steps 3–5) and let it recover.

## Related

- `docs/architecture/metrics.md` — every custom metric, its labels, and the
  cardinality/PII rules they obey
- [ADR-0067](../decisions/0067-domain-prometheus-metrics.md) — why the
  counters look like this
- `docs/runbooks/steam-gifts.md` — the feature these checks belong to
- `docs/runbooks/traffic-surge.md` — how to query our Prometheus, and the
  other rate-limit mechanism
- `docs/architecture/cache-keys.md` — `gifts:steam_profile:*`, the cache whose
  hit rate this runbook reads
