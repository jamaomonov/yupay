# Async fulfilment: move the saga off the payment webhook

**Date:** 2026-08-31
**Status:** Accepted, not implemented
**Scope:** One feature flag · a split inside `fulfillment.start_for_order` (plan vs execute) · the first real Dramatiq actor in `apps/worker` · a reconciler job in `apps/scheduler` · tests · docs
**Touches:** `fulfillment` (service split + a concurrency guard in `process_task`), `apps/worker` (new actor module), `apps/scheduler` (new job), `core.config` (one flag)
**Builds on:** ADR-0013 (§"Migration to async worker" — this implements it), ADR-0047/0062 (the risk gate sits before fulfilment and is untouched)

## Problem

`payments.service` runs the whole fulfilment saga **inside the acquirer's
webhook request**: `PerformTransaction` arrives → we mark the payment
succeeded → `start_for_order` plans tasks and then calls each supplier over
HTTP, in-process, before the webhook can answer
(`payments/service.py:525`, `fulfillment/service.py:416`).

Three things are wrong with that, in increasing order of urgency:

1. **The acquirer's patience bounds our supplier's latency.** A supplier
   that thinks for ten seconds makes Payme/Click/Uzum time out, mark the
   callback failed and retry it — duplicate work on a money path, saved
   today only by idempotency and suppliers being fast.
2. **It caps throughput at the slowest supplier.** Webhook workers are
   busy waiting on third-party HTTP; at the AGENTS.md target of 1–5k
   orders/day this is the first thing that falls over.
3. **It blocks the Merchant API.** A machine client cannot hold a
   connection open while we shop at a supplier; asynchronous delivery with
   webhooks is a precondition for that whole feature.

ADR-0013 called this shot in May: _"The synchronous-saga shortcut … must
move to the worker before launch."_ The worker container has been deployed
and idle ever since — `apps/worker/.../tasks/` contains one `__init__.py`,
and the broker (`dramatiq_broker_url`, Redis DB 1) is already configured.

## The insight the design leans on

**`fulfillment_tasks` already is the outbox.** ADR-0013's table has
`status='pending'`, `attempts_count`, and a `next_attempt_at` column that
today has no reader outside an analytics query. `start_for_order` already
creates those rows _in the caller's transaction_ — the same transaction
that records the payment success. So the hard half of the transactional
outbox pattern (atomically persisting "work to do" with the money write) is
**already shipped and battle-tested**. What is missing is only the second
half: someone other than the webhook to execute the pending rows.

No new table. No new state machine. The Dramatiq message is a _nudge_, not
the source of truth — the rows are.

## Design

### 1. The flag

`fulfilment_async: bool = Field(default=False)` in `core.config`
(env `FULFILMENT_ASYNC`). Default off: the deploy that ships this changes
production behaviour by zero bytes. Rollback at any moment is an env flip
and restart, not a redeploy.

Two processes branch on it — api (`start_for_order`) and scheduler (the
reconciler). The worker deliberately does NOT: it always processes whatever
pending tasks exist, so a mid-flight flag flip can never strand work the
api already enqueued. All three share
`yupay.core.config.Settings`, but each container loads its own env file: the
flip instruction in the runbook must name every file the variable lands in
(verify the compose `env_file` wiring during implementation — api and
scheduler may or may not share one).

### 2. `start_for_order` splits into plan + execute

Public signature unchanged (`(db, *, order_id) -> list[FulfillmentTask]`),
exactly as ADR-0013 promised. Internally:

- **Planning** (unchanged, both modes): load order + items, resolve
  sourcing per SKU, create missing `FulfillmentTask` rows, order
  `paid → fulfilling`, publish the status event. All inside the caller's
  transaction — atomic with the payment success that triggered it.
- **Execution branch:**
  - flag **off** → loop `process_task(db, task_id=...)` in-process.
    Today's behaviour, byte for byte.
  - flag **on** → leave the tasks `pending` and fire the nudge:
    `process_order.send(order_id)` — best-effort, wrapped in
    `contextlib.suppress(Exception)` with a warning log. A lost nudge is
    not lost work (§4); a nudge that arrives before the caller's COMMIT
    finds no committed tasks and no-ops (§3), so ordering against the
    commit needs no post-commit hook machinery.

Both callers get the right behaviour for free:

- **Payment webhook** — answers the acquirer in milliseconds; the saga
  runs in the worker.
- **Admin releasing a held order** (`/orders/{id}/release`) — same
  function, so with the flag on the release also enqueues. The route
  already returns the task list; tasks now come back `pending` instead of
  terminal. The admin UI copy for the release action must say "выдача
  запущена" rather than implying completion — one string, three locales
  if it is user-visible i18n (it is admin-only; admin UI is Russian-only
  today — verify and follow what exists).

### 3. The actor — `apps/worker/src/yupay_worker/tasks/fulfillment.py`

```python
@dramatiq.actor(queue_name="fulfillment", max_retries=3, min_backoff=5_000)
def process_order(order_id: str) -> None:
    asyncio.run(_process_order(order_id))
```

- **Sync shell, async core.** Dramatiq actors are sync; the shell calls
  `asyncio.run` on the async core. The core opens its **own engine with
  `NullPool`** per invocation: an asyncio pool cannot be shared across
  `asyncio.run` event loops, and at single-digit orders/minute a
  connection per message is the honest, simple choice. Revisit only with
  measurements.
- **The core is idempotent and lock-guarded:** select this order's
  runnable tasks — `status='pending'`, plus retryable failures whose
  `next_attempt_at <= now()` (the exact status a retryable failure leaves
  behind is whatever `process_task` writes today; the plan reads it from
  the code rather than this spec guessing) — with
  **`FOR UPDATE SKIP LOCKED`**, and run the existing
  `process_task(db, task_id=...)` on each. Zero rows → log, exit cleanly.
  This single guard makes every duplicate-delivery source harmless: a
  premature nudge (before commit), a Dramatiq redelivery, a reconciler
  re-enqueue racing the original, two workers — whoever locks first works,
  everyone else skips.
- **No new execution logic.** `process_task` is untouched except for
  whatever the FOR-UPDATE loading requires; the failure cascade
  (cancel/refund on non-retryable failure, admin alerts, low-balance
  warnings) already lives inside it and runs identically in the worker.
  Verified cross-process safe: realtime events go through Redis pub/sub
  (`realtime/service.py`), Telegram alerts and delivery notifications are
  plain HTTP — nothing in the saga touches request-scoped state.
- `apps/worker/main.py` imports the tasks module so the actor registers;
  the `ping` smoke actor stays.

### 4. The reconciler — `apps/scheduler/.../jobs/fulfillment_reconcile.py`

Every minute (pattern: the existing timeout sweeps): find tasks that are
`pending` older than `fulfilment_stale_after` (setting, default 120 s) —
or retryable with `next_attempt_at <= now()` — whose order is still
`fulfilling`, and re-send `process_order` for their (distinct) order ids,
bounded per tick.

This is the safety net that makes the nudge allowed to be best-effort:
Redis lost the message, the worker crashed mid-batch, the enqueue call
itself failed — the reconciler re-nudges within two minutes, and the SKIP
LOCKED guard makes the re-nudge safe. It also gives `next_attempt_at` its
first real reader: retryable failures today wait for a human on the admin
retry button; with the reconciler they retry themselves on schedule
(`process_task` already writes `next_attempt_at`; nothing consumed it).

Runs only when `fulfilment_async` is on — flag off means no pending rows
ever outlive their request, and a sweep would only mask bugs.

### 5. What visibly changes

- An order spends observable time in `fulfilling`. Both storefronts
  already handle this — they poll order status with backoff and subscribe
  over WebSocket, because manual-fulfilment SKUs park in `in_progress`
  today. No frontend change.
- The stuck-order watchdog (`stuck_orders.py`) becomes the second net
  behind the reconciler: a task that keeps failing retryably still pages a
  human on the existing schedule. No change needed — but the runbook gains
  a section on reading the new queue (what `pending` beyond 2 minutes
  means, how to check worker liveness, what the reconciler covers).

### What deliberately does NOT change (YAGNI)

- **No per-task actors, no tenacity, no purgatory circuit breakers** —
  ADR-0013 step 3 stays future work; one actor per order processing tasks
  sequentially matches today's semantics exactly and is enough at today's
  volume.
- No LISTEN/NOTIFY, no priority queues, no scheduler-jobs migration into
  the worker.
- `retry_task`/`bulk_retry_tasks` (admin) keep executing inline — an admin
  clicking retry wants the result now, and volume is human-scale.
- Wallet top-ups: untouched (they never enter the saga).
- Held orders: untouched (the risk gate runs before `start_for_order`
  either way).

## Failure modes, named

| Failure                                | Behaviour                                                                                                                                                                                                   |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Redis down at enqueue time             | nudge suppressed + warning; reconciler re-nudges ≤ 2 min                                                                                                                                                    |
| Worker down                            | tasks sit `pending`; reconciler re-nudges (into the dead broker) until worker returns; watchdog pages at its threshold                                                                                      |
| Worker crashes mid-batch               | locked rows unlock on connection drop; Dramatiq redelivers; SKIP LOCKED dedupes                                                                                                                             |
| Nudge arrives before COMMIT            | actor sees no committed pending tasks, no-ops; reconciler covers the order after commit                                                                                                                     |
| Duplicate nudges (retry + reconciler)  | FOR UPDATE SKIP LOCKED — second consumer skips                                                                                                                                                              |
| Supplier fails non-retryably in worker | same cascade as today (`process_task` owns it): cancel, refund, alert                                                                                                                                       |
| Flag flipped off mid-flight            | in-flight worker batches finish; new payments execute inline; stranded `pending` rows (enqueued but unprocessed at the flip) are visible to the watchdog and runnable via admin retry — document in runbook |

## Testing

- Existing suite runs with the flag **off** and must pass untouched — that
  is the regression proof that off-mode is byte-identical.
- New unit/integration, flag on:
  - `start_for_order` plans and leaves tasks `pending`; order is
    `fulfilling`; no supplier call happened (assert on the mock fulfiller).
  - The actor's async core, invoked directly (no real broker): processes
    pending tasks to `delivered` through the same fixtures the sync tests
    use; a second invocation no-ops; invocation with no committed tasks
    no-ops.
  - SKIP LOCKED: two concurrent core invocations on one order — every task
    processed exactly once (testcontainers, two sessions).
  - Reconciler: selects the stale pending and the due-retry task; ignores
    fresh pending, terminal tasks, and orders no longer `fulfilling`;
    bounded per tick.
  - Enqueue failure: Redis send raising does not fail the payment webhook.
- Coverage: `fulfillment` is in the ≥95 % list (§8) — the new branches
  must not drop it.

## Rollout

1. Deploy, flag off. Nothing changes. Verify the worker container is
   healthy and drains a `ping` message on prod.
2. Flip `FULFILMENT_ASYNC=true` (api env) + restart api. Watch one live
   order end-to-end; watch the reconciler stay idle (nothing stale).
3. Rollback at any point: flag off + restart. Stranded `pending` rows, if
   any, finish via admin retry.

## Open questions (defaults chosen, none blocking)

- **Queue depth visibility:** the runbook gets the SQL for "pending older
  than N"; a Grafana panel over it is a follow-up, not part of this.
- **`fulfilment_stale_after` at 120 s** is deliberately conservative
  against the enqueue-before-commit race (a webhook transaction should
  commit in well under a second); tune down later if the two-minute worst
  case for a lost nudge ever matters commercially.
