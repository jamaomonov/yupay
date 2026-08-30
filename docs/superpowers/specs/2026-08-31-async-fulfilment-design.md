# Async fulfilment: move the saga off the payment webhook (Postgres-native queue)

**Date:** 2026-08-31 (rewritten same day: Postgres queue instead of Dramatiq — see "Why not the broker we already have")
**Status:** Accepted, not implemented
**Scope:** One feature flag · a split inside `fulfillment.start_for_order` (plan vs execute) · a NOTIFY on commit · a consumer loop that becomes the worker's entrypoint · tests · docs (incl. the AGENTS.md stack row)
**Touches:** `fulfillment` (service split + task-claiming query), `apps/worker` (new entrypoint, Dramatiq scaffolding retired), `core.config` (two settings), `infra/docker/worker.Dockerfile` (CMD), AGENTS.md §2
**Builds on:** ADR-0013 (§"Migration to async worker" — this implements its intent with a simpler carrier), ADR-0047/0062 (the risk gate runs before fulfilment; untouched)

## Problem

`payments.service` runs the whole fulfilment saga **inside the acquirer's
webhook request**: `PerformTransaction` arrives → payment marked succeeded →
`start_for_order` plans tasks and then calls each supplier over HTTP,
in-process, before the webhook can answer (`payments/service.py:525`,
`fulfillment/service.py:416`).

Three things are wrong with that, in increasing order of urgency:

1. **The acquirer's patience bounds our supplier's latency.** A supplier
   that thinks for ten seconds makes Payme/Click/Uzum time out and retry
   the callback — duplicate work on a money path, saved today only by
   idempotency and suppliers being fast.
2. **It caps throughput at the slowest supplier.** Webhook workers sit in
   third-party HTTP waits; at the AGENTS.md target of 1–5k orders/day this
   is the first thing that falls over.
3. **It blocks the Merchant API.** A machine client cannot hold a
   connection open while we shop at a supplier; asynchronous delivery is a
   precondition for that feature.

ADR-0013 called this in May: _"the synchronous-saga shortcut … must move to
the worker before launch."_ The worker container has been deployed and idle
ever since.

## The insight the design leans on

**`fulfillment_tasks` already is the queue.** ADR-0013's table has
`status='pending'`, `attempts_count`, and a `next_attempt_at` column whose
only reader today is an analytics query. `start_for_order` already creates
those rows **in the caller's transaction** — the same transaction that
records the payment success. The hard half of a reliable queue — atomically
persisting "work to do" with the money write — has been shipped and
battle-tested since May.

What is missing is only a consumer that is not the webhook. Everything else
in this spec is plumbing for that consumer.

## Why not the broker we already have

The first draft of this spec used the deployed-but-idle Dramatiq/Redis
worker. Rewritten after weighing the operator's own criteria (survive a
spike; don't break; be easy to fix when broken):

- **A spike is absorbed by the table, not the transport.** Orders pile up
  as rows and drain at supplier speed whichever transport nudges the
  consumer — the transports do not differ on the criterion that mattered
  most.
- **One system of record beats two kept in sync.** The Redis variant spent
  a whole failure-modes table on truth-vs-nudge divergence (nudge before
  commit, Redis blink, reconciler races). With Postgres carrying both, the
  commit _is_ the publication: `NOTIFY` inside a transaction is delivered
  only on commit, by definition. That entire class of failure modes is not
  mitigated — it is gone.
- **The queue lands in the backups.** `pg_dump → age → R2` already covers
  `fulfillment_tasks`; restore a backup and undelivered orders resume by
  themselves. No broker's queue is in those backups.
- **The codebase is async; Dramatiq actors are not.** The sync-shell /
  `asyncio.run` bridge worked but was pure impedance tax.
- **Latency is a wash.** `LISTEN/NOTIFY` wakes the consumer within
  single-digit milliseconds of the commit — indistinguishable from a Redis
  push, and invisible anyway behind supplier calls measured in seconds.
- Industry has quietly converged here for exactly this shape of workload:
  `FOR UPDATE SKIP LOCKED` (Postgres 9.5, 2016) underlies River (Go),
  pg-boss (Node), Oban (Elixir), and Rails 8's default Solid Queue.

Dramatiq is retired from the stack, not merely bypassed: dead scaffolding
contradicts repo hygiene, and AGENTS.md's own rule says update it when the
stack changes. If a broker is ever genuinely needed, the swap is one
consumer file — the tables and `process_task` never learn the difference.
Temporal remains the named future for multi-step sagas, unchanged.

## Design

### 1. The flag

`fulfilment_async: bool = Field(default=False)` (env `FULFILMENT_ASYNC`).
Default off: the deploy that ships this changes production behaviour by
zero bytes; rollback is an env flip + api restart, not a redeploy.

Only the **api** branches on it (in `start_for_order`). The worker loop
deliberately does not: it always drains whatever runnable tasks exist, so a
mid-flight flip can never strand work the api already planned. The
scheduler is not involved at all (§3 explains where the reconciler went).

### 2. `start_for_order` splits into plan + execute

Public signature unchanged (`(db, *, order_id) -> list[FulfillmentTask]`).
Internally:

- **Planning** (both modes, unchanged): load order + items, resolve
  sourcing, create missing `FulfillmentTask` rows, order
  `paid → fulfilling`, publish the realtime status event — all inside the
  caller's transaction, atomic with the payment success.
- **Execution branch:**
  - flag **off** → loop `process_task(db, task_id=...)` in-process.
    Today's behaviour, byte for byte.
  - flag **on** → leave the tasks `pending` and, in the same transaction,
    `SELECT pg_notify('fulfillment_queue', :order_id)`. Postgres holds the
    notification until COMMIT and drops it on ROLLBACK — the
    nudge-outruns-the-commit race and the phantom nudge for a rolled-back
    order are impossible by construction, not by mitigation.

Both callers get correct behaviour for free: the payment webhook answers
the acquirer in milliseconds; an admin releasing a held order
(`/orders/{id}/release`) enqueues the same way — the route already returns
the task list, now in `pending`. The admin release copy must say the work
was _started_, not completed (admin UI is Russian-only; follow what
exists).

### 3. The consumer — the worker's new job

`apps/worker/src/yupay_worker/consumer.py`, an asyncio loop that becomes
the container's entrypoint (`CMD ["python", "-m", "yupay_worker.consumer"]`
replacing `CMD ["dramatiq", "yupay_worker.main", ...]` in
`infra/docker/worker.Dockerfile`; the `make dev-worker` target updated to
match).

One process, one loop:

1. **Listen:** a dedicated raw asyncpg connection executes
   `LISTEN fulfillment_queue`. (Dedicated and raw on purpose: a LISTEN
   connection must live outside any pool and never be recycled mid-wait.)
2. **Wait** on either a notification or a timeout of
   `fulfilment_poll_seconds` (setting, default **5**). The timeout tick IS
   the reconciler: it catches notifications lost to a worker restart and
   picks up retryable tasks whose `next_attempt_at` came due — merged into
   the same loop instead of living in the scheduler, because a poller and
   a reconciler that are the same three lines should not be two
   deployable units.
3. **Claim and run:** in its own session (normal pooled engine — one
   long-lived event loop, so the asyncio pool is safe here), select
   runnable tasks — `status='pending'`, plus retryable failures with
   `next_attempt_at <= now()` (the exact status a retryable failure
   leaves behind is whatever `process_task` writes today; the plan reads
   it from code) — with **`FOR UPDATE SKIP LOCKED`**, bounded batch, and
   run the existing `process_task(db, task_id=...)` on each. Zero rows →
   back to waiting.
4. **Graceful shutdown:** SIGTERM finishes the task in hand, then exits;
   an interrupted task's row lock releases with the connection and the
   next tick reclaims it.

`SKIP LOCKED` is the whole concurrency story: duplicate notifications, a
second worker replica, the poll tick racing a notification — whoever locks
first works, everyone else skips. Scaling later = more replicas of the same
container, zero code change.

**No new execution logic.** `process_task` keeps owning the failure cascade
(cancel/refund on non-retryable failure, alerts, low-balance warnings) and
runs identically here — verified cross-process safe: realtime events go
over Redis pub/sub, Telegram and delivery notifications are plain HTTP,
nothing in the saga touches request-scoped state.

### 4. What visibly changes

- An order spends observable time in `fulfilling` (typically well under a
  second of queue time plus the supplier's own latency, which dominates
  today too). Both storefronts already poll with backoff and subscribe over
  WebSocket — manual-fulfilment SKUs park in `in_progress` today, so the UI
  state exists. No frontend change.
- The buyer-facing paradox worth stating: the acquirer confirms payment
  _faster_ (the webhook no longer waits on suppliers), and the code arrives
  a breath later over WS — subjectively an improvement.
- The stuck-order watchdog (`stuck_orders.py`) stays the human-paging net
  behind the loop's own retry tick. The runbook gains: what a `pending`
  task older than a minute means, how to check worker liveness, the one SQL
  for queue depth.

### What deliberately does NOT change (YAGNI)

- No per-task parallelism inside an order, no circuit breakers per supplier
  (ADR-0013 step 3 stays future work) — sequential per order matches
  today's semantics exactly.
- Admin `retry_task`/`bulk_retry_tasks` keep executing inline: a human
  clicking retry wants the result now, at human volume.
- Wallet top-ups never enter the saga; held orders keep waiting for the
  risk gate's release. Both untouched.
- The scheduler gains nothing and loses nothing.

## Failure modes, named

| Failure                                         | Behaviour                                                                                                                                    |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Transaction rolls back after planning           | NOTIFY never fires (held until commit), rows never exist — nothing to clean                                                                  |
| Worker down                                     | tasks sit `pending`; on restart the first poll tick drains the backlog; the watchdog pages at its threshold if that takes too long           |
| Worker crashes mid-task                         | row lock dies with the connection; next tick reclaims; `fulfillment_attempts` shows the partial history                                      |
| Notification lost (worker restarting at commit) | poll tick picks the task up within `fulfilment_poll_seconds`                                                                                 |
| Two workers / duplicate wake-ups                | `SKIP LOCKED` — first claims, second skips                                                                                                   |
| Supplier fails non-retryably                    | same cascade as today, now from the worker: cancel, refund, alert                                                                            |
| Retryable supplier failure                      | `process_task` sets `next_attempt_at` as today; the poll tick is now its reader — retries happen on schedule instead of waiting for an admin |
| Flag flipped off mid-flight                     | worker drains what exists (it does not branch on the flag); new payments execute inline; nothing strands                                     |
| LISTEN connection dies                          | loop detects, reconnects with backoff; the poll tick covers the gap meanwhile                                                                |

## Testing

- The existing suite runs flag-off, untouched — the regression proof that
  off-mode is byte-identical.
- New, flag on:
  - `start_for_order` plans, leaves tasks `pending`, calls no supplier
    (assert on the mock fulfiller), and the NOTIFY rides the transaction
    (send, roll back, assert a listener observes nothing).
  - The consumer's claim-and-run core, invoked directly: drains pending
    tasks to `delivered` through the same fixtures the sync tests use; a
    second invocation no-ops; `SKIP LOCKED` proven with two concurrent
    sessions on one order — every task processed exactly once
    (testcontainers).
  - The poll tick picks up a due `next_attempt_at` retry and ignores
    fresh/terminal tasks.
  - Listener reconnect: kill the LISTEN connection, assert the loop
    recovers and a subsequent notification is received.
- Coverage: `fulfillment` is in the ≥95 % list (§8); the new branches must
  hold it.

## Rollout

1. Deploy, flag off. The worker container now runs the consumer loop
   against an empty queue — verify it is healthy and its LISTEN is
   established (one startup log line says so).
2. Flip `FULFILMENT_ASYNC=true` in the api env + restart api (the flag
   lives only there — the worker does not read it). Watch one live order
   end-to-end; watch queue depth stay at zero.
3. Rollback at any point: flag off + api restart. In-flight worker tasks
   finish; nothing strands.

## Documentation obligations

- AGENTS.md §2 stack row: "Background work: Postgres-native queue
  (`FOR UPDATE SKIP LOCKED` + `LISTEN/NOTIFY`) consumed by `apps/worker`;
  Dramatiq retired 2026-08; Temporal remains the deferred option for
  multi-step sagas."
- ADR (new, short): the carrier decision and why the deployed Dramatiq was
  retired unused — future maintainers deserve the reasoning, not just the
  diff.
- Runbook: queue-depth SQL, worker liveness, the flag's env file, what
  `pending` means and for how long it is normal.

## Open questions (defaults chosen, none blocking)

- `fulfilment_poll_seconds = 5`: with LISTEN doing the real-time work the
  poll is a net, not a latency path; 5 s bounds notification loss without
  meaningfully loading the DB (one indexed query per tick — reuse or add
  the partial index on pending tasks if none fits; the plan checks).
- Queue-depth Grafana panel: follow-up, not part of this; the runbook SQL
  comes first.
