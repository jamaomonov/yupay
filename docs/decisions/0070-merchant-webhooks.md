# 0070 — Merchant outgoing webhooks: an outbox on Postgres, a connect-time address check, and a three-valued delivery fact

- Status: accepted
- Date: 2026-09-08
- Spec: `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md` §10
- Plan: `docs/superpowers/plans/2026-09-07-merchant-b2b-m3a.md`
- Predecessors: ADR-0064 (the Postgres fulfilment queue this copies), ADR-0068
  (the M1 foundation), ADR-0069 (the machine API this is the other direction of)

## Context

M2 gave a reseller a surface to call. M3a gives us one to call **theirs**: a
merchant registers one https endpoint and we POST a signed JSON body to it when
an order's status moves or support credits their deposit.

That inverts the trust story of everything else in this repo. Until now every
outbound HTTP call went to a supplier or an acquirer **we** chose, at an address
in our own configuration. Here the destination is a string a third party typed
into a form, fetched by `apps/worker` — a process that runs inside the Docker
network beside Postgres, Redis and MinIO. Two more things change with it: the
receiver is code nobody but its owner can redeploy (ADR-0069 decision 1's
constraint, now pointed the other way), and a delivery can fail in ways where we
do not know whether it arrived.

The wire contract third parties implement against lives in
`apps/api/src/yupay/modules/merchants/README.md` — headers, canonical string, an
executed worked example, the retry schedule — and is deliberately not duplicated
here. This ADR records the seven choices a future maintainer would otherwise
re-litigate.

## Decisions

### 1. The outbox is a Postgres table drained by `apps/worker`, not a broker

`merchant_webhook_deliveries` is ADR-0064's shape, copied on purpose down to the
details: a row with a claimable `status`, inserted **in the transaction that
causes the event**, claimed with `FOR UPDATE SKIP LOCKED`, one `SAVEPOINT` per
row, and a `pg_notify` that rides the same transaction so a nudge can neither
outrun the fact behind it nor survive that fact being rolled back.

A broker (Redis Streams, NATS, RabbitMQ) would have made the enqueue a second
system's write inside our transaction — which is either a dual-write with a
window where an order commits and its event is lost, or an outbox anyway with a
relay on top. ADR-0064 already paid for this pattern, the operational surface
is a table an on-call engineer can read with `psql`, and the delivery log the
cabinet renders from M4 is the same rows. One less moving part in a
single-VPS deployment that must stay horizontally splittable.

What it costs: the queue's latency floor is the worker's poll tick when a
NOTIFY is lost to a restart (`fulfilment_poll_seconds`, default 5), and the
backlog of a disabled hook sits in a partial index rather than in a broker's
dead-letter queue. Both are cheaper than a second piece of infrastructure.

### 2. The address is re-checked **at connect time**, because the save-time check cannot be enough

`merchants.admin.set_webhook` refuses a URL that is not https or that names a
non-public host, through the very function the catalog's image URLs go through
(`catalog.image_url_safety.validate_public_https_url`) — one blocked-range table
in the repo, not two that drift. That check is real and it is not the control.
Its own module docstring says why, and this is the sentence the whole of
`core/outbound.py` exists for:

> It cannot detect **DNS rebinding**: a hostname that resolves to a public IP
> right now (when this validator runs) but to a private/loopback/metadata IP at
> the moment Next's image optimizer actually fetches it. Closing that residual
> risk requires the fetcher itself to re-resolve and re-check the IP at request
> time (or pin the resolved IP), which is Next's image optimizer's
> responsibility, not this validator's — Next does not offer a hook for it.

For catalog images that residual risk is still open, because Next owns the
fetcher. **Here we own the fetcher.** `core.outbound.post_json` resolves the
host itself, refuses unless _every_ answer is public, aims the request at the
checked address as a literal (carrying the hostname in `Host` and TLS SNI so
certificate verification still happens against the name), and watches httpcore's
`connect_tcp` trace to refuse if the socket layer is ever handed anything else.
No redirects, `trust_env=False`, no connection pooling between calls, a total
wall-clock budget, a cap on **wire** bytes and no decompression.

The two functions are deliberately **not** merged into one entry point. That one
parses notation at save time; this one checks resolved addresses at connect time.
Folding them together would let an edit to one silently change the other, and
the save-time half would start reading as a control it is not.

### 3. `Delivery` is three-valued, because a boolean collapses the case that matters

Every `OutboundError` carries `delivery: NOT_SENT | UNKNOWN | RECEIVED`
(`core/outbound_errors.py`), and the retry table reads that attribute rather
than matching on exception names.

A boolean "did it arrive" has to file a timeout under "no". But a timeout is the
one failure where the request demonstrably went out: a merchant answering in
eleven seconds against a ten-second budget has already provisioned the order.
Two of the three answers are therefore not "no", and a policy that cannot tell
them apart either re-delivers events merchants already processed or refuses to
retry things that never left the process.

The **families** stay two-wide (`OutboundRefusedError` — it ended on our side;
`OutboundUnreachableError` — it ended on theirs) so a caller matching on them
cannot miss a branch, and the delivery question is answered by the attribute
instead. A test walks `OutboundError.__subclasses__()` and insists every leaf
declares one, so a new failure mode cannot be added without deciding what it
means for a retry.

### 4. `RECEIVED` is terminal — and it is the rule an integrator's own retry logic must not undo

If their server took the request and answered, a retry sends a **second copy of
an event they already processed**. That is the one failure mode a retry policy
must never cause, so `Delivery.RECEIVED` is terminal whatever else is true of
the error: it outranks the family, and it is checked first in
`webhook_retry.decide_failure`. The two leaves that reach it today
(`ResponseTooLargeError`, `ContentEncodingNotAllowedError`) mean the delivery
landed and the _answer_ was unusable.

What we do not pretend to fix is `UNKNOWN`. We retry it, because that is what a
webhook is, and the honest name for the guarantee is **at-least-once**. What
makes it usable rather than a warning is that the delivery row's id is stable
across every retry of that row, travels in `X-Yupay-Delivery`, and is inside the
**signed** material — an unsigned header is worthless against a replay, and
after the first integrator this could not have been added without a
`/merchant/v2`. `order.status_changed` carries no event id in its payload (that
would have broken the exact-key-set rule §10 rests on), so the delivery id is
the receiver's only dedupe handle.

Ordering follows from the same place. The claim orders by
`next_attempt_at, created_at, id`; the `id` term is load-bearing because both
timestamps default to `CURRENT_TIMESTAMP`, which in Postgres is the
**transaction start**, so the `paid` and `fulfilling` rows one placement writes
are byte-identical in both columns. `id` is a uuid7, so it encodes enqueue
order. That fixes the tie and **not** global ordering: a retried event lands
after events enqueued behind it, which is inherent to per-row backoff. Receivers
are told, in those words, to order by the payload's `at`, dedupe on the delivery
id, and expect `paid` after `delivered`.

### 5. One queue, one task — and a dying loop must be loud

`apps/worker` now drains two queues. They run in **separate asyncio tasks**, not
in one awaited `gather`, because a gather returns with its slowest member: the
webhook drain's duration would become the fulfilment queue's polling period. The
real shape is a re-enabled hook with a large backlog against a slow-but-healthy
merchant, which can drain for hours with every paid order waiting behind it.
Measured with fakes, a 3 s webhook drain cut fulfilment drains in a 6 s window
from 116 to 8.

Each queue gets its own concurrency dial (`merchant_webhook_concurrency`,
default 2, beside `fulfilment_concurrency`, default 4) because the thing that
hangs is different — a supplier there, a stranger's web server here — and its own
`asyncio.Event`, because one event shared between two consumers is a lost
wake-up: the first loop to return clears a flag the second has not read.

Moving the loops into tasks removed the thing that used to make a dead queue
visible, which was the crash taking the process down. So `shutdown.supervise`
puts it back deliberately: a loop that dies **or merely returns** logs
`worker.consumer.queue_loop_died`, sets the shared stop event so its siblings
wind down, and makes `run()` return `1` — which `consumer.py`'s
`if __name__ == "__main__"` guard passes to `sys.exit`, so
`restart: unless-stopped` restarts the container. The alternative is a
healthy-looking process with the money path stopped, and nothing to see it.

### 6. Two event types, and `balance.low` was dropped

`order.status_changed` and `balance.credited` are the complete v1 vocabulary
(spec §10). `balance.low` was in an earlier draft and the owner dropped it: a
threshold we choose, evaluated on our schedule, that fires against somebody
else's idea of "low" — and a merchant who wants it can compute it from
`balance_usd`, which rides both `GET /merchant/v1/me` and every order response.

The vocabulary is enforced at the `enqueue` boundary and re-checked at send
time, and `merchant_webhook_deliveries.event_type` deliberately carries **no**
CHECK constraint: adding a third event stays a code change rather than a
migration on a table that only grows. The send-time re-check is not
belt-and-braces — the canonical string's safety rests on `event_type` being a
closed ASCII vocabulary, because an event type carrying an LF could move a field
boundary.

### 7. Configuration is admin-only until M4's cabinet

`PUT`/`GET`/`DELETE /admin/merchants/{id}/webhook` and
`POST .../webhook/rotate-secret` are the whole configuration surface, all
admin-gated. There is deliberately **no** `/merchant/v1` write for it, and the
reason is not sequencing: the only thing such an endpoint would buy is letting a
stranger aim our own worker at an address of their choosing, which is decision 2
re-opened as a feature. The owner wants it self-serve from the merchant's own
cabinet in M4, where a session and a human are behind the change.

The consequence, stated rather than discovered: a pilot cannot receive webhooks
until support sets their URL, and the runbook carries the recipe.

## Consequences

- **`INVENTORY_ENC_KEY` is now load-bearing for a _third_ subsystem.** Voucher
  codes, merchant API-key secrets (ADR-0069 decision 4), and now webhook signing
  secrets, each under its own HKDF purpose label
  (`yupay:merchants:webhook:v1`) derived from that one input. Rotate or lose it
  and deliveries cannot be signed at all — `crypto.decrypt` raises, the drain's
  poison belt writes the row `failed`, and the merchant's failure budget is
  deliberately untouched because the fault is ours. The runbook's entry is now
  titled for three subsystems.
- **The two queues share one DB connection pool.** Peak concurrent sessions in
  the worker is `fulfilment_concurrency + merchant_webhook_concurrency` — 4 + 2
  where it was 4. Nobody has checked that against the configured pool size on
  prod, and the failure mode is a **checkout timeout**, not anything that looks
  like a worker problem. Check it before the deploy, not after.
- **`worker.consumer.queue_loop_died` wants an alert rule.** The exit code only
  helps if something notices the restart loop; the alert lives outside this
  repo.
- **Nothing has been delivered to a real remote host.** Every test is loopback
  or stubbed, on purpose. Two questions only a staging run answers, and they go
  together: `AI_ADDRCONFIG` combined with the client's no-fallback address pin
  (glibc-in-container does not count loopback as a configured address, and the
  behaviour is glibc-version-dependent), and whether the worker really exits
  inside Docker's `stop_grace_period` on a real SIGTERM with a live Postgres and
  a real G2B pool.
- **A merchant whose server gzips regardless of `Accept-Encoding` sees every
  delivery recorded as refused**, terminally, because a `RECEIVED` refusal is
  decision 4. That is correct and it is support-visible; the runbook names it.
- **A queued delivery keeps the URL it was enqueued with.** The row snapshots
  `url` so the log can answer "we recorded a 200 — to which of their hosts?",
  which means correcting a wrong endpoint re-enables the hook but does **not**
  re-aim the backlog. A merchant who moved hosts should be told to expect the
  old rows to fail out rather than arrive.
- **While a hook is disabled, new events are not queued at all.** The producer
  treats "no hook" and "disabled hook" as one outcome — the outbox holds only
  deliverable work — so re-enabling resumes the rows queued _before_ the
  disable and nothing else. The gap is invisible to the merchant unless they
  poll, which is why the contract says the order read is the source of truth.
- **A disabled hook's backlog never expires.** Rows stay `pending` and
  unclaimed forever if the merchant never comes back, so a hook re-enabled after
  a week delivers a week-old `paid`. M4's cabinet is where "discard the backlog"
  would belong if anyone wants it.
- **There is no automatic terminal-failure event.** The seam fires where the
  order's status actually moves, and a permanent fulfilment failure moves the
  _task_, not the order: a reseller sees `paid → fulfilling → silence`, and only
  a support-closed order emits `failed`. The contract says so, so that nobody
  builds a timeout they should not need; M3b's stall visibility is the real fix.
- **`response_body` is text a merchant's server wrote**, stored to 2048
  characters and rendered in M4's cabinet. Whoever builds that screen owns the
  escaping.
- **The auto-disable notice is Russian-only**, like every other template in this
  module. An English-speaking integrator gets a Russian email.
- **There are no queue metrics.** The delivery log answers "what happened to
  this event"; nothing answers "how deep is the queue" but a SQL query, which
  the runbook now carries. A Prometheus counter (ADR-0067's pattern) is the
  obvious follow-up before a pilot depends on this.
- **The auto-disable threshold is a guess.** 20 consecutive failed _attempts_ is
  a setting for that reason; the first pilot's real numbers should be looked at.
