# Runbook — Postgres-native fulfilment queue

`fulfillment_tasks` is the queue (ADR-0064). With `fulfilment_async=true`,
`start_for_order` leaves each task `pending` and fires `pg_notify` on
commit; `apps/worker`'s `yupay_worker.consumer` claims and runs them via
`fulfillment.service.drain_pending_tasks` (`FOR UPDATE SKIP LOCKED`) on
`fulfilment_concurrency` parallel drainers, woken instantly by
`LISTEN fulfillment_queue` with a poll tick
(`fulfilment_poll_seconds`, default 5s) as the restart-proof fallback. With
the flag off (the default everywhere except prod), `start_for_order` still
runs tasks inline in the same request, exactly as before this ADR — the
worker container runs the same consumer loop regardless, it just finds an
empty queue. **One caller ignores the flag entirely:** the merchant machine
API always enqueues — see "The merchant channel does not read the flag" below.

## The flag

- **Env var**: `FULFILMENT_ASYNC`. **Home: `secrets/api.env` on prod only.**
  Prod compose mounts that same file into api, worker, scheduler, and bot
  (`docker-compose.prod.yml`'s `env_file: ./secrets/api.env` on all four),
  so the variable _is_ present in the worker's environment once it's set
  there — it just has no effect on the worker: only `api`
  (`fulfillment.service.start_for_order`) ever branches on
  `settings.fulfilment_async`. The worker always drains whatever rows
  exist regardless of the flag's value.
- Changing it requires an **api restart**, not a worker restart —
  `Settings` is read once at process start.
- Default `false` everywhere. Dev/staging exercise the async path through
  `apps/api/tests/integration/test_fulfillment_async.py` instead of running
  with the flag on.

## The merchant channel does not read the flag

**`POST /merchant/v1/orders` is always asynchronous**, whatever
`FULFILMENT_ASYNC` is set to. `merchants/orders.py::_enqueue_only` passes
`start_for_order` a settings copy with the flag on, and that is a call-site
decision rather than an operator's, because with it off the supplier purchase
would run **inside the transaction that debits the reseller's deposit**:
`process_task` catches only `FulfillerError` / `FulfillerNotIntegratedError`,
so anything raising after the supplier is paid and before the commit rolls back
the order, the debit and the delivery while the supplier keeps the money — and
the merchant, following our published contract, retries the same
`merchant_order_id`, finds nothing, and buys it twice.

Two operational consequences:

- **The merchant channel depends on the worker being up**, always, not only
  after the flag is flipped. A stalled worker shows as merchant orders sitting
  in `fulfilling`; the deposit is correctly debited and every row is present,
  so nothing is lost and nothing needs reconstructing — but nothing is
  delivered either, and resellers are told to poll.
- **A pending-queue backlog can be entirely merchant orders even with the flag
  off.** When triaging depth, do not conclude the flag got flipped:

  ```sql
  SELECT o.merchant_id IS NOT NULL AS is_merchant, count(*)
  FROM fulfillment_tasks t JOIN orders o ON o.id = t.order_id
  WHERE t.status = 'pending' GROUP BY 1;
  ```

Rolling the flag back (see "Rollback") therefore does **not** return merchant
orders to inline fulfilment, and must not be attempted as a way to do so.

## The worker drains a second queue

Since M3a Task 4 the same **process** also drains `merchant_webhook_deliveries`
on `LISTEN merchant_webhook_queue` — outgoing merchant webhooks. Its
operational side (the failure streak, the auto-disable and the one way to
re-enable a hook) is in `docs/runbooks/merchant-b2b.md`.

Each queue runs in its **own asyncio task**, with its own tick, its own LISTEN
connection and its own concurrency. That is load-bearing rather than tidy: with
both queues drained inside one awaited `gather` the call returns with its
slowest member, so a webhook drain that takes minutes would become the
fulfilment queue's polling period — and a re-enabled hook with a large backlog
against a slow-but-healthy endpoint can drain for hours. If you ever see paid
orders sitting undelivered while the webhook queue is deep, that coupling is
what to check for first; it is regression-tested
(`apps/worker/tests/test_consumer.py::test_a_slow_queue_does_not_pace_the_other`,
which measures the coupled shape as its own control).

A NOTIFY on **either** channel still wakes both queues — an empty one answers 0
on its first claim and returns, which costs less than routing wake-ups by
channel — but each queue owns its own `asyncio.Event`, because one shared event
between two consumers is a lost wake-up.

So the fulfilment queue's own behaviour is unchanged, with one honest caveat:
the two queues share this process's DB connection pool and event loop. Sizing
is `fulfilment_concurrency + merchant_webhook_concurrency` sessions at peak,
not `fulfilment_concurrency`.

**A dead queue now takes the container down.** `run()` supervises its loop
tasks: one that raises, or returns without a stop signal, is logged as
`worker.consumer.queue_loop_died` and the process exits **1** so
`restart: unless-stopped` restarts it. Alert on that line — it is the one
shape where fulfilment stops while the container still reads healthy.

**Shutdown is bounded at 8 s** (`SHUTDOWN_BUDGET_SECONDS`), of which the first
3 go to a queue loop caught mid-drain and the rest to in-flight notification
sends. It is 8 rather than 10 because Docker's default `stop_grace_period` is
10 s and neither compose file overrides it for `worker`: a shutdown that spends
the whole grace period is SIGKILLed with `close_g2b_pool()` and
`worker.consumer.stopped` still to come. A cancelled drain is safe — the batch
rolls back and its rows return to `pending`.

**At deploy:** the `worker.consumer.started` log line's `concurrency=<int>`
field became `queues={"fulfillment": 4, "merchant_webhook": 2}`. Nothing in
this repo reads it, but a Grafana or Loki panel outside the repo might. Three
other lines are new: `worker.consumer.queue_loop_died` (above — worth an
alert), `worker.consumer.shutdown_left_draining` when SIGTERM arrives
mid-drain, and a `crashed=` field on `worker.consumer.stopped`.

## The worker's own settings

None is gated by `FULFILMENT_ASYNC` — the worker drains whatever exists, so all
apply from the moment it starts.

| Setting                        | Env                            | Default | What it does                                                                                                                                                                                                     |
| ------------------------------ | ------------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fulfilment_poll_seconds`      | `FULFILMENT_POLL_SECONDS`      | `5`     | Poll tick, shared by both queues. `LISTEN` does the real-time work; the tick catches notifications lost to a restart and is the retry cadence for a dropped `LISTEN` connection.                                 |
| `fulfilment_concurrency`       | `FULFILMENT_CONCURRENCY`       | `4`     | Fulfilment drainers per wake, each on its own DB session and connection. Raising it costs pool connections; lowering it to 1 means one hung supplier call stalls the whole queue.                                |
| `merchant_webhook_concurrency` | `MERCHANT_WEBHOOK_CONCURRENCY` | `2`     | The same dial for the webhook queue, separate because what hangs there is a **third party's** server. Two attempts to one endpoint still serialise at commit, which bounds how hard one queue hits one merchant. |

All are read once at worker start — changing any needs a **worker** restart
(unlike `FULFILMENT_ASYNC`, which only the api reads).

## Checking queue depth

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT count(*) FROM fulfillment_tasks WHERE status = 'pending';"

docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT id, order_id, supplier, created_at, now() - created_at AS age
   FROM fulfillment_tasks
   WHERE status = 'pending'
   ORDER BY created_at
   LIMIT 1;"
```

The first query is the headline number for a dashboard or a quick check
before restarting anything (see below). The second gives the oldest pending
row's age — the number that actually says whether the worker is keeping up:
a queue can have a nonzero count and still be healthy (a burst just landed
and hasn't been claimed yet), but an old oldest-pending row is not.

**No automated queue-depth alert exists yet** — the two queries above are a
manual check today. `infra/prometheus/alerts/api.yml` has a note explaining
why the old Dramatiq-era queue-depth rule couldn't fire and never watched
anything real; a proper alert on `fulfillment_tasks` pending-row age/count
is a real follow-up candidate, not yet built.

**`pending` older than a minute means the worker is down or drowning.**
Normal automatic fulfilment lands in low hundreds of milliseconds (dev smoke
measured ~565ms paid → delivered end-to-end over the `LISTEN` wake path);
even the poll-tick fallback bounds a cold start to `fulfilment_poll_seconds`
(5s default). A `pending` row a minute old or older is outside both of
those, so before touching anything: check the worker's logs.

```bash
docker compose -f docker-compose.prod.yml logs worker --tail 100
```

Look for `worker.consumer.drain_failed` (an infra-level exception —
Postgres connectivity, an unhandled error escaping `drain_pending_tasks`'s
own per-task savepoint) or `worker.consumer.listen_failed` (the `LISTEN`
connection dropped; the poll tick keeps working, just slower, until the
next `ensure()` reconnects). A worker stuck on one slow/hanging supplier
call inside a single claimed task also shows as a growing queue with no
error at all. That task stalls **its own drainer** for as long as the call
hangs: the per-task savepoint isolates errors, not latency. The other
`fulfilment_concurrency` − 1 drainers (default 4 total) keep claiming and
running everything else, so a single hung call costs you a quarter of the
throughput, not the queue. A hang resolves on its own when the supplier
client's own timeout fires; a whole batch hitting the same slow supplier
will still look like the queue stalled, so check for a supplier incident
before assuming the worker itself is broken.

**Lock order (invariant worth protecting):** everything that touches both
locks **fulfilment task rows before the order row**. The drain loop conforms
for free — it claims tasks with `FOR UPDATE SKIP LOCKED`, which never waits,
and only then locks the order to settle. The refund and order-failed /
order-cancelled cascades conform because they call
`cancel_open_tasks_for_order` before any write to the order row (the status
write, and the `OrderEvent` insert's `FOR KEY SHARE` on it). So a refund
racing a drainer over the same order **queues, it does not deadlock**.

If you ever see a Postgres deadlock in `worker.consumer.drain_failed` or on
an admin refund, that invariant has been broken by a new code path — find
the path that touches the order row before the tasks rather than treating
the deadlock as noise. It is not self-healing on the money side: an aborted
admin refund has already called the acquirer, but its rollback discards the
`last_refund` replay guard, so retrying it blindly can refund twice
upstream. Check the acquirer before re-clicking.

## Worker liveness

- **Log line**: `worker.consumer.started` on process start (carries
  `poll_seconds` and `concurrency`). Its absence after a deploy or restart means the process
  never got past setup — check for an import/config error in the same log
  tail. `worker.consumer.stopped` on clean shutdown.
- **Container status**:
  ```bash
  docker compose -f docker-compose.prod.yml ps worker
  ```
  `unless-stopped` restarts it on crash; a container flapping between
  `Up` and `Restarting` alongside a growing queue depth (above) is the
  worker crash-looping, not merely lagging — check `docker compose ...
logs worker` for the exception right before each restart.

## Shutdown behaviour (SIGTERM)

The consumer's stop check only runs between wakes, not inside one: once a
`LISTEN` wake or poll tick starts a drain, all `fulfilment_concurrency`
drainers keep claiming and running batches of 20 until the queue comes back
empty, regardless of a pending `SIGTERM`. **On shutdown, the worker
finishes draining the entire pending backlog before it exits** — shutdown
latency scales with backlog size, not with a fixed timeout. After the last
batch it also waits up to 5s for in-flight notification sends (the
"delivered" Telegram pings the final commit kicked off, which would
otherwise be cancelled with the process); it logs
`worker.consumer.awaiting_stray_tasks` with a count when it does.

This matters because Compose's default stop grace period is **10 seconds**:
`docker compose stop` / `up -d` on a deploy sends `SIGTERM`, waits 10s, then
`SIGKILL`s anything still running. A worker mid-drain on a large backlog
(a burst of orders, or a queue that built up while the worker was down) can
exceed that window and get killed mid-batch. That is not data loss — a
killed connection drops its row locks and the next start (or another
replica) reclaims exactly where it left off, per ADR-0064 — but it does mean
an unusually long restart, or one `worker.consumer.drain_failed`-free
`SIGKILL` with no `worker.consumer.stopped` line, is expected under a large
backlog rather than a sign of a bug. **Check queue depth before restarting
the worker** (see above) if you want a clean, prompt shutdown rather than a
kill.

## Rolling out (operator steps)

1. **Before deploying the worker**, count what is already `pending`:

   ```bash
   docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
     "SELECT count(*) FROM fulfillment_tasks WHERE status = 'pending';"
   ```

   The worker drains any committed `pending` row from its very first tick,
   flag or no flag. Rows left `pending` by the old synchronous path (a
   crashed request, a task stranded by an incident) would therefore be
   fulfilled — codes issued, customers notified — the moment the worker
   starts. Expect zero; if it is not zero, look at what those rows are and
   decide deliberately before starting the worker.

2. Deploy with the flag still **off**. The worker runs the consumer against
   an empty queue; confirm the `worker.consumer.started` line (it carries
   `poll_seconds` and `concurrency`).

3. Flip `FULFILMENT_ASYNC=true` in `secrets/api.env` and restart **api**
   only. Then watch two live orders through, not one:
   - a **card** order (Click/Payme/Uzum → webhook → queue), and
   - a **wallet-balance** order.

   The wallet case is genuinely different: `payments.service.create_intent`
   settles a wallet payment synchronously inside the customer's own request,
   with no webhook anywhere. With the flag on, that request now returns the
   order as `fulfilling` instead of `delivered`, and the codes land a moment
   later via the worker and the realtime push. That is expected — but it is
   the customer-visible difference the flag makes, so see it once yourself.
   Queue depth should touch zero between orders.

   Watch the delivered transition **on the customer's screen**, not only in
   the admin. The first flip (2026-08-31) surfaced a client-side freeze: both
   surfaces suppressed REST polling entirely while the order-updates socket
   reported connected, but a WebView suspended during the external payment
   hop leaves a zombie socket that still reports connected — the delivered
   push died in it and the Mini App sat on «Выдаём заказ» until a manual
   reload. Since then the clients poll through `paid → fulfilling →
fulfilled` even with a live socket (`orderRefetchInterval` in the Mini
   App, `orderPollInterval` in web) — the socket accelerates, the poll
   reconciles, mirroring this queue's own NOTIFY-plus-poll design. A frozen
   "fulfilling" screen returning means that reconciler regressed.

## Rollback

Flag off + api restart:

```bash
sed -i 's/^FULFILMENT_ASYNC=.*/FULFILMENT_ASYNC=false/' secrets/api.env
docker compose -f docker-compose.prod.yml up -d --force-recreate api
```

The worker keeps running either way — it isn't what the flag gates — and
drains whatever is already `pending` from before the rollback, so nothing
already queued is stranded. After the flag flips off, every _new_ task goes
back to running inline in the api request, and the queue depth should settle
to zero as the worker finishes the leftovers.

## Related

- [ADR-0064](../decisions/0064-postgres-fulfilment-queue.md) — why the
  table is the queue, and why Dramatiq was retired instead of finished
- `docs/architecture/module-map.md` — the `fulfillment -.-> worker`
  out-of-process dependency
- `apps/worker/README.md` — the consumer's own short description
- `apps/api/tests/integration/test_fulfillment_async.py` — the NOTIFY
  commit/rollback test the design rests on
