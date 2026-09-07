# apps/worker — YuPay background workers

Postgres-queue consumer. `src/yupay_worker/consumer.py` drains **two** queues
on one loop:

- **`fulfillment_tasks`** on `LISTEN fulfillment_queue` — see
  `yupay.modules.fulfillment.service`'s NOTIFY-on-commit. Concurrency:
  `fulfilment_concurrency` (default 4).
- **`merchant_webhook_deliveries`** on `LISTEN merchant_webhook_queue` — the
  outgoing merchant webhooks (M3a). Concurrency:
  `merchant_webhook_concurrency` (default 2). Its own dial because what hangs
  here is a **third party's** server, not a supplier we chose.

A poll tick (`fulfilment_poll_seconds`) catches notifications lost to a
restart. Both listeners share **one** wake event, so any notification drains
both queues — an empty queue costs one indexed query and returns, which is
cheaper and far harder to get wrong than routing wake-ups by channel. Every
wake fans out to each queue's `concurrency` drainers, each on its own session,
so one hanging call stalls one drainer instead of the queue —
`FOR UPDATE SKIP LOCKED` keeps their claims disjoint without any coordination.

The rows in those tables are the queues themselves — this process holds no
state worth preserving and can be killed at any moment.

`Queue` (name, channel, drain, concurrency) is what makes that parameterised
rather than duplicated; a third queue is a fourth entry in `_queues()`, and its
channel constant must be imported from the module that NOTIFYs it, never
respelled here.

## Run locally

```bash
make dev-worker
```
