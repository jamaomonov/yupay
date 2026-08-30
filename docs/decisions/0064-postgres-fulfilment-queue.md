# 0064. Postgres-native fulfilment queue replaces Dramatiq

- **Status**: Accepted
- **Date**: 2026-08-31
- **Deciders**: @jamaomonov
- **Tags**: backend | infra | data

## Context and problem statement

`start_for_order` has always run the fulfilment saga inline, inside the
payment webhook handler — a synchronous supplier call sits between the
acquirer's callback and its HTTP response. `dramatiq[redis,watch]` has been a
dependency since the initial bootstrap commit, with a Redis broker wired into
every compose file and every secrets template, but no actor was ever written
against it: `apps/worker` had no entrypoint of its own, and nothing enqueued
a job. The dependency was fully deployed and fully idle — a second broker, a
second at-least-once delivery story, and a second thing that can silently
fall out of sync with the database, carried for a migration that never
happened.

Meanwhile `fulfillment_tasks` already exists, already gets a row per
`OrderItem` inside the same transaction as the payment, and already carries
everything a queue needs: a status column, a claim predicate, a created-at
ordering. The question was never "should fulfilment move off the request
path" — it should — but "onto which of the two systems already staged for
the job."

## Decision drivers

- **One system of record.** A Dramatiq job and a `fulfillment_tasks` row are
  two representations of the same fact ("this item needs fulfilling"). Keeping
  both means keeping them consistent — the truth-vs-nudge class of bug: the
  DB row says one thing, the queue message says another, and something has to
  reconcile them on every crash and every retry.
- **Backups already cover the queue.** `pg_dump` backs up Postgres; nothing
  backs up Redis's job payloads (`docker-compose.prod.yml` runs it
  `--appendonly yes` for durability, not archival). A table that already
  rides the nightly Postgres backup needs no separate durability story for
  the queue it doubles as.
- **Async-native.** `asyncpg`/SQLAlchemy 2 async are already the only
  supported DB path (AGENTS.md §6: "Async everywhere on the request path").
  Dramatiq's worker model is sync-first; the actor would have needed its own
  event loop bridge to call back into the async ORM session the rest of
  `fulfillment.service` already uses.
- **`NOTIFY`-on-commit kills the truth-vs-nudge class outright.** `pg_notify`
  called inside the same transaction as the row insert is delivered by
  Postgres on `COMMIT` and dropped on `ROLLBACK` — there is no way for the
  nudge to outrun the fact it announces, or to survive a fact that never
  landed. A Dramatiq `.send()` after `db.commit()` cannot make that
  guarantee: the process can die between the two calls, either enqueuing a
  message for a row that never committed or committing a row nothing ever
  wakes up for.

## Considered options

1. **Finish the Dramatiq integration** — write the actor, enqueue from
   `start_for_order`, keep the Redis broker.
2. **Postgres-native queue** — `fulfillment_tasks` stays `pending`, `NOTIFY`
   on commit, a `SELECT ... FOR UPDATE SKIP LOCKED` claim loop in
   `apps/worker` drains it.
3. **Temporal** — durable multi-step saga execution with built-in retry/
   compensation semantics.

## Decision outcome

**Chosen option: 2.** `start_for_order` splits into plan (unchanged — create
the tasks, atomic with the payment) and execute: with `fulfilment_async`
off (the default), execute runs inline exactly as before, so the deploy that
ships this changes production behaviour by zero bytes. With the flag on,
execute is skipped and the transaction instead calls
`pg_notify('fulfillment_queue', order_id)`. `apps/worker` is a small asyncio
loop (`yupay_worker.consumer`) that holds a `LISTEN fulfillment_queue`
connection for instant wake-ups, falls back to a poll tick
(`fulfilment_poll_seconds`, default 5s) for a notification lost to a
restart, and claims work with `drain_pending_tasks`
(`fulfillment.service`, `FOR UPDATE SKIP LOCKED` on `status='pending'`,
ordered by `created_at`, batch size 20). Each wake fans out to
`fulfilment_concurrency` (default 4) drainers, each on its own session:
`SKIP LOCKED` already makes their claims disjoint, so parallelism needs no
coordination, and without it one supplier call hanging for 20s would stall
every order behind it — the savepoint around each task isolates errors, not
latency. A crashed worker's row locks die
with its connection; the next tick or a second replica reclaims them for
free — nothing about the queue's correctness depends on the worker process
staying alive.

Dev smoke test (flag on): paid → delivered in ~565ms via the `LISTEN` wake
path, well under the 5s poll fallback that would otherwise bound it.

The spec `apps/worker` was to replace assumed `process_task` writes
`next_attempt_at` on a retryable failure, with the poll tick reading it back
to drive scheduled retries. It does not: grepping the module turns up zero
assignments to that column outside the 0008 migration and the (read-only)
ops-analytics query. The claim predicate is therefore `status='pending'`
alone, in both modes — a `failed` task waits for the existing admin retry
button (`POST /admin/fulfillment/tasks/{id}/retry` → `retry_task`, which
still flips the row to `pending` and calls `process_task` inline,
unchanged by this ADR) exactly as it did before. Building scheduled retries
was out of scope here and remains a real gap the column's presence
overstates — a candidate for a follow-up, not something this migration
silently added.

Option 3 (Temporal) was rejected for this cut: fulfilment today is a single
supplier call per task, not a multi-step, long-running saga with
human-in-the-loop steps — the class of problem Temporal earns its
operational weight for. It remains the documented option once fulfilment
grows compensating steps across multiple suppliers or a saga that needs to
survive a multi-day pause (see AGENTS.md §2). Option 1 was rejected on the
decision drivers above: it would have kept paying the two-systems-of-record
cost indefinitely for a broker with, as of this decision, zero actors ever
shipped against it.

### Positive consequences

- One dependency removed outright (`dramatiq[redis,watch]`), one broker
  connection string removed from every env template and compose file.
- The queue rides the existing Postgres backup/restore story
  (`infra/backup/`) with no new mechanism to build or test.
- `NOTIFY`-on-commit means the fastest path (an idle worker, no backlog) is
  bounded by network + wake latency, not by a poll interval — measured
  ~565ms end-to-end in dev.
- A poisoned task (an unexpected exception past `process_task`'s own
  handled `FulfillerError`/`FulfillerNotIntegratedError` cases) is contained
  per-task by a `SAVEPOINT` inside `drain_pending_tasks`: it lands `failed`
  through the existing admin retry path instead of crashing the batch or
  livelocking the queue on a retry loop.
- Redis keeps exactly the jobs it always genuinely had — rate-limit state
  and `realtime`'s pub/sub fan-out (`fulfillment/service.py`'s
  `_publish_status_changed` → `realtime.publish_order_event`) — not a
  second, redundant job queue.

### Negative consequences

- No scheduled retry exists for a `failed` task in either mode — see above.
  This was already true before this ADR; it is now explicit instead of
  implied by an unused column.
- `apps/worker` currently runs a single replica in both compose files;
  `FOR UPDATE SKIP LOCKED` makes a second replica safe to add, but nothing
  today exercises that path under load.
- **Wallet-balance checkout changes what the customer sees.** The drivers
  above are argued over acquirer webhooks, but the wallet gateway has no
  webhook: `payments.service.create_intent` settles it synchronously inside
  the customer's own request and calls `start_for_order` there. With the
  flag on, that request returns the order as `fulfilling` instead of
  `delivered`, and the codes follow a moment later over the worker + realtime
  push. Nothing is lost and no money moves differently — but it is the one
  place where flipping the flag is visible to a customer mid-request, so the
  rollout watches a wallet order as well as a card order (see the runbook's
  flip checklist). Covered by
  `test_payments_wallet_gateway.py::test_wallet_checkout_returns_fulfilling_when_async_is_on`.
- Shutdown latency now scales with backlog size: on `SIGTERM` the consumer
  finishes draining whatever batch it is mid-loop on before the process
  exits (see the runbook) — a large backlog can outlast a short orchestrator
  grace period (Compose's default is 10s).

## Validation

`apps/api/tests/integration/test_fulfillment_async.py::test_notify_rides_the_transaction`
is the load-bearing test: it asserts the commit/rollback semantics the whole
design rests on against a real `LISTEN`er, not a mock — a `NOTIFY` inside a
transaction that rolls back must never arrive, and one inside a transaction
that commits must arrive promptly. `drain_pending_tasks`'s `SKIP LOCKED`
claim (two real sessions racing one backlog), its per-task savepoint
isolation, and the lock that stops an admin cancel overwriting a task the
consumer just succeeded are covered by real-database integration tests in
`apps/api/tests/integration/test_fulfillment_async.py`. The consumer loop
itself has **unit** coverage only — `apps/worker/tests/` is fakes, no
database: the wake/tick race, the listener's never-raise reconnect, the
fan-out to K drainers on K sessions, and the shutdown window for in-flight
notification sends. Nothing automated exercises the real consumer process
against a real queue; that was covered once, by hand, in the dev smoke run
(paid → delivered in ~565ms). With
`fulfilment_async` off, the entire pre-existing fulfilment suite
(`test_fulfillment_routes.py`, `test_fulfillment_service_paths.py`,
`test_fulfillment_manual_paths.py`, `test_admin_fulfillment_bulk_routes.py`,
`test_fulfillment_list_ordering.py`, and every payment/affiliate test that
walks an order paid → delivered) passes unmodified — the regression proof
that flag-off behaviour is byte-identical to before this ADR.

## References

- `docs/superpowers/specs/2026-08-31-async-fulfilment-design.md` — full
  design and the two spec corrections (`next_attempt_at`, `retry_task`)
  folded into the Decision outcome above
- [ADR-0013](./0013-fulfillment-skeleton-and-provider-stubs.md) — original
  fulfilment skeleton; this ADR changes only where tasks execute, not the
  `Fulfiller` contract or the FSM
- `docs/runbooks/fulfillment-queue.md` — operating the queue: depth checks,
  worker liveness, the flag's home, rollback
- `docs/architecture/module-map.md` — the `fulfillment -.-> worker`
  out-of-process dependency this ADR introduces
