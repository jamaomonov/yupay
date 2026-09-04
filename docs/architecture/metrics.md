# Prometheus metrics catalogue

> Every **custom** metric emitted by any app must appear in this file, with its
> full label vocabulary. New metrics without a row here are rejected in code
> review — the same rule `cache-keys.md` applies to Redis keys, and for the
> same reason: a label set is a contract with a store that has no schema.

## The two rules

**1. A label value is bounded, and is never about a person.** Prometheus keeps
one time series per distinct label combination, in memory, for the life of the
process, and neither Prometheus nor Grafana has a redactor, a TTL, or access
control worth the name. So a label value must be drawn from a small set we
choose ourselves. Never a label:

- anything unbounded — an id, a URL, a link, a vanity name, a search term, an
  order number, a raw error message;
- anything identifying — an email, a phone, a Telegram user id, a steamid64, a
  nickname, an **IP**. AGENTS.md §9 bans these from logs; metrics are worse,
  because a log line ages out of Loki and a series does not.

If you need per-subject attribution, that is a log (hashed — see
`core.logging.hash_short`) or the edge access log, not a label. The
`steam-web-api-quota.md` runbook is written that way on purpose: it reads the
_shape_ from metrics and finds the _client_ in Loki.

**2. Recording never fails a request.** Increments go through
`yupay.core.metrics`, whose recorders swallow everything a registry can throw
and log `metrics.increment_failed`. A counter is an observation about the
work, never part of it — see ADR-0067.

Both rules are asserted, not just reviewed:
`apps/api/tests/unit/test_metrics_labels.py` fails if a counter grows a label
outside the allowlist or if a recorder can raise.

## Where they are defined

`apps/api/src/yupay/core/metrics.py` — all of them, in one file, so the whole
label vocabulary is reviewable at once. Modules import a recorder; they never
build a `Counter` of their own.

## The catalogue

| Metric                                   | Type    | Labels                                                                                                                                  | Emitted by                                                    | Why it exists                                                                                                                                                                                  |
| ---------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `yupay_steam_web_api_calls_total`        | counter | `endpoint` = `resolve_vanity_url` \| `get_player_summaries`; `consumer` = `gifts_profile` \| `auth_signin`; `outcome` = `ok` \| `error` | `auth.steam.resolve_persona`, `gifts.profile._resolve_vanity` | The Steam Web API key has a **100k/day ceiling shared by both consumers**. Sum across `consumer` for the ceiling; split by it to attribute a burn.                                             |
| `yupay_gifts_steam_profile_checks_total` | counter | `verdict` = `found` \| `not_found` \| `unsupported` \| `unavailable`; `source` = `cache` \| `steam` \| `local`                          | `gifts.profile.check_steam_profile`                           | The verdict mix (an `unavailable` spike is Steam trouble; a `not_found` spike is abuse or a broken client) and cache effectiveness, which is the early sign of someone walking distinct links. |

Cardinality: 2 × 2 × 2 + 4 × 3 = **20 series** at the theoretical maximum, of
which **13 (~65%) ever appear** — the rest are combinations the code itself
never produces:

- `resolve_vanity_url` is only ever called with `consumer="gifts_profile"`
  (`gifts.profile._resolve_vanity` hardcodes it — `auth.steam.resolve_persona`
  is the only caller that ever passes `consumer="auth_signin"`, and it only
  calls `get_player_summaries`). The `resolve_vanity_url` × `auth_signin` pair
  (2 `outcome` series) never appears, leaving 6 of the first counter's 8.
- `source="cache"` can only carry `verdict="found"` or `verdict="not_found"`:
  those are the only two verdicts `_cache_verdict` ever writes — `unavailable`
  is never cached (it is our own failure, not a fact about the profile) and
  `unsupported` never reaches the cache branch at all (an `s.team` link
  returns before any cache read). `source="local"` is narrow the other way —
  only `unsupported` (an `s.team` link) or `unavailable` (no API key
  configured) — and `source="steam"` never carries `unsupported`, since that
  verdict always short-circuits before a Steam call. That leaves 2 + 3 + 2 = 7
  of the second counter's 12.

6 + 7 = 13.

`outcome` is about the **call**, not the answer: a 200 whose body we could not
trust still spent quota, and shows up as an `unavailable` verdict on the other
counter instead. And per the bullet above, the cache hit rate is
`cache / (cache + steam)` — counting `local` as a miss would make a flood of
friend links read as a cache collapse.

## What is _not_ here

Per-route request counts, status classes and latency histograms
(`http_requests_total`, `http_request_duration_seconds`) come from
`prometheus_fastapi_instrumentator`, wired up in `bootstrap.create_app`. They
are not listed above because we do not choose their labels; the bucket bounds
we do choose are pinned by `apps/api/tests/unit/test_metrics_buckets.py`.

Process, Postgres, Redis, container and host metrics come from the exporters
listed in `infra/prometheus/prometheus.yml`.

## Consumers

- Dashboards: `infra/grafana/dashboards/*.json` (provisioned from file; the
  Steam counters are on `yupay-steam-quota`).
- Alerts: `infra/prometheus/alerts/*.yml`. A rule must watch a metric
  something actually emits —
  `apps/api/tests/unit/test_alert_rules.py::test_no_rule_watches_a_metric_nothing_emits`
  exists because one once did not.
- Runbooks: `docs/runbooks/steam-web-api-quota.md`.
