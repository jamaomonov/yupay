# Runbook — Postgres-native fulfilment queue

`fulfillment_tasks` is the queue (ADR-0064). With `fulfilment_async=true`,
`start_for_order` leaves each task `pending` and fires `pg_notify` on
commit; `apps/worker`'s `yupay_worker.consumer` claims and runs them via
`fulfillment.service.drain_pending_tasks` (`FOR UPDATE SKIP LOCKED`), woken
instantly by `LISTEN fulfillment_queue` with a poll tick
(`fulfilment_poll_seconds`, default 5s) as the restart-proof fallback. With
the flag off (the default everywhere except prod), `start_for_order` still
runs tasks inline in the same request, exactly as before this ADR — the
worker container runs the same consumer loop regardless, it just finds an
empty queue.

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
error at all — that task holds up nothing else in the same batch (each
claimed task runs independently), but a full batch of 20 all hitting the
same slow supplier will look like the whole queue stalled; check for a
supplier incident before assuming the worker itself is broken.

## Worker liveness

- **Log line**: `worker.consumer.started` on process start (carries
  `poll_seconds`). Its absence after a deploy or restart means the process
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

The consumer's stop check only runs between batches, not inside one: once a
`LISTEN` wake or poll tick starts a drain, the inner loop
(`while await drain_pending_tasks(db) > 0`) keeps claiming and running
batches of 20 until the queue comes back empty, regardless of a pending
`SIGTERM`. **On shutdown, the worker finishes draining the entire pending
backlog before it exits** — shutdown latency scales with backlog size, not
with a fixed timeout.

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
