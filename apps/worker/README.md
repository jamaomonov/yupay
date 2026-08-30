# apps/worker — YuPay background workers

Postgres-queue consumer. `src/yupay_worker/consumer.py` drains
`fulfillment_tasks` rows: `LISTEN fulfillment_queue` wakes the loop the
instant a task is planned (see `yupay.modules.fulfillment.service`'s
NOTIFY-on-commit), and a poll tick (`fulfilment_poll_seconds`) catches
notifications lost to a restart. Every wake fans out to
`fulfilment_concurrency` (default 4) drainers, each on its own session, so
one hanging supplier call stalls one drainer instead of the queue —
`FOR UPDATE SKIP LOCKED` keeps their claims disjoint without any
coordination. The rows in `fulfillment_tasks` are the queue itself — this
process holds no state worth preserving and can be killed at any moment.

## Run locally

```bash
make dev-worker
```
