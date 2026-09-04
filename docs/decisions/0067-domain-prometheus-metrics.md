# 0067. Domain Prometheus counters live in `core.metrics`, with closed label vocabularies

- **Status**: Accepted
- **Date**: 2026-09-04
- **Deciders**: @jamaomonov
- **Tags**: backend | infra | observability | security

## Context and problem statement

Until now the API exported exactly one family of metrics: what
`prometheus_fastapi_instrumentator` produces in `bootstrap.create_app` —
per-route request counts, status classes and latencies. That answers "how
often was this route called and how fast was it", and nothing else.

`POST /gifts/steam-profile` is the case that made the gap concrete. It is
unauthenticated, rate-limited per IP only (120/min, bucket
`gifts-steam-profile`), and every **distinct** link it is handed costs one or
two calls against a Steam Web API key with a 100 000/day ceiling — a key
**Steam sign-in shares**. Only `found`/`not_found` verdicts are cached (6h),
so distinct links are free of the cache by construction.

None of that is an emergency: exhausting the key makes checks answer
`unavailable` (non-blocking — buyers can still pay) and sign-ins go nameless.
That is precisely the problem. It degrades silently, and the HTTP metrics show
a healthy 200 the whole way down. A reviewer called it "a lever a bored person
can pull, and worth a counter before it is the thing nobody can explain."

So: what shape does the first domain metric take, given that it will set the
convention for every one after it?

## Decision drivers

- **A shared quota needs an addable denominator.** The ceiling applies to the
  key, not to either consumer, so the gift check and sign-in must increment
  the _same_ counter and differ only by a label.
- **Labels are a permanent, un-redactable store.** Prometheus keeps one series
  per label combination in memory for the process's life. The obvious "useful"
  labels here — the invite link, the vanity name, the steamid64, the nickname,
  the IP — are each unbounded _and_ each identify a third party who is not our
  customer. This module already refuses to put any of them in a log line
  (`hash_short(identifier)`); a metric is worse than a log, because a log line
  ages out of Loki and a series does not.
- **This endpoint's standing rule is that it must never be the reason a sale
  fails.** Observability does not get an exception. A counter that can raise
  would add a failure mode to the exact path it was added to watch.
- **No new infrastructure.** The scrape, the datasource, the dashboard
  provisioner and the alert pipeline all exist. Whatever we choose has to ride
  them.

## Considered options

1. **`prometheus_client` counters in a single `core.metrics` module**, with
   `Literal`-typed label vocabularies and non-raising recorders.
2. **Counters defined next to the code that increments them** (in
   `gifts/profile.py`, `auth/steam.py`).
3. **Structured logs + a Loki recording rule** instead of a metric.
4. **A dedicated exporter / OpenTelemetry metrics pipeline.**

## Decision outcome

**Chosen option: 1.** Two counters —
`yupay_steam_web_api_calls_total{endpoint,consumer,outcome}` and
`yupay_gifts_steam_profile_checks_total{verdict,source}` — defined in
`apps/api/src/yupay/core/metrics.py`, exposed on the existing `/metrics`
endpoint, with:

- **closed `Literal` label vocabularies**, so mypy (not code review) is what
  stops a caller passing a vanity name where a verdict goes, and every
  possible series is enumerable in advance (20 at the theoretical maximum);
- **recorders that never raise** — a broken registry degrades to one
  `metrics.increment_failed` warning and a missing data point;
- **an explicit `consumer` argument** on `auth.steam.resolve_persona`,
  required rather than defaulted, because a default is how a future call site
  hides inside another's quota number.

`prometheus-client` moves from a transitive dependency of the instrumentator
to a declared one; no version changes (`uv.lock` gains two lines). Code that
imports a package declares it.

### Positive consequences

- A quota burn is now visible _before_ the key is spent, attributable to a
  consumer, and explainable: verdict mix says what buyers were told, cache hit
  rate says whether the traffic was distinct links.
- One place to review the entire label vocabulary
  (`docs/architecture/metrics.md` is its prose form), which is the only way
  the cardinality/PII rule stays enforceable as more metrics land.
- Two `warn` alerts and a Grafana dashboard on infrastructure that already
  existed; nothing new to deploy or scrape.

### Negative consequences

- Every module that wants a metric now touches a shared file, which will grow.
  Accepted deliberately: the review value of one file listing every label
  outweighs the coupling, and the file is a leaf (it imports only the logger).
- `resolve_persona` gained a required keyword argument — a small,
  compile-time-checked break for two call sites.
- Aggregated counters cannot answer "which IP did this"; that stays a Loki
  question. This is a feature, not a gap — see the drivers.

## Validation

- `apps/api/tests/unit/test_metrics_labels.py` fails if a counter grows a
  label outside the allowlist, if a vocabulary stops being a small `Literal`,
  or if a recorder can raise.
- `apps/api/tests/integration/test_gifts_steam_profile_metrics.py` asserts
  every verdict moves the counter with the right `source`, that a cache hit
  spends no quota, and that a registry throwing on every increment changes no
  verdict and fails no request.
- `apps/api/tests/integration/test_auth_steam.py` asserts sign-in increments
  the same counter under `consumer="auth_signin"` — the half of the shared
  denominator the gift tests cannot see.
- Operationally: the next time the recipient check misbehaves, the answer
  should come from the `yupay-steam-quota` dashboard rather than from a
  guess.

## Alternatives considered (detail)

### Option 2 — counters next to their call sites

Pros: locality; a module owns its instrumentation. Cons: the label vocabulary
becomes un-reviewable in aggregate, which is exactly where the cardinality and
PII mistakes get made — nobody reviewing a two-line diff in `profile.py`
notices that `steam_id` just became a label. Rejected on that alone.

### Option 3 — logs plus a Loki recording rule

The events are already logged, so this looked free. But Loki is the wrong
store for a rate that must be alertable and cheap to query over 24 hours,
the shared box has a documented history of a disk fill wedging Loki
(`prod-shared-host-observability`), and it would have coupled quota alerting
to log retention. Logs remain the right tool for the per-subject question the
metrics deliberately cannot answer.

### Option 4 — a dedicated exporter or the OTel metrics pipeline

The `opentelemetry-*` packages are already dependencies (tracing), so a metrics
pipeline was available. Rejected as a second metrics path to operate, scrape
and reason about, for a counter that the existing `/metrics` endpoint exports
for free. AGENTS.md's "no new dependency or exporter if the repo already has a
way" applies squarely.

## References

- [ADR-0066](./0066-steam-gifts-live-catalog.md) — the Steam Gifts feature the
  recipient check belongs to
- `docs/architecture/metrics.md` — the catalogue and the two rules
- `docs/runbooks/steam-web-api-quota.md` — what a spike means and what to do
- AGENTS.md §9 (never log PII), §10 (performance/observability)
