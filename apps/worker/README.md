# apps/worker — YuPay background workers

Postgres-queue consumer. `src/yupay_worker/consumer.py` drains
`fulfillment_tasks` rows: `LISTEN fulfillment_queue` wakes the loop the
instant a task is planned (see `yupay.modules.fulfillment.service`'s
NOTIFY-on-commit), and a poll tick (`fulfilment_poll_seconds`) catches
notifications lost to a restart. The rows in `fulfillment_tasks` are the
queue itself — this process holds no state worth preserving and can be
killed at any moment.

## Run locally

```bash
make dev-worker
```
