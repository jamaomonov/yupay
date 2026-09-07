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

**Each queue runs in its own asyncio task**, with its own loop. Not tidiness:
`asyncio.gather` returns with its slowest member, so draining both queues in
one awaited call made the webhook drain's duration the fulfilment queue's
polling period — a re-enabled hook with a large backlog against a
slow-but-healthy endpoint would have stalled every paid order behind it for as
long as that took. Regression-tested in
`tests/test_consumer.py::test_a_slow_queue_does_not_pace_the_other`, which
measures the coupled shape as its own control rather than asserting a bare
number.

A poll tick (`fulfilment_poll_seconds`) catches notifications lost to a
restart. A notification on **either** channel wakes **every** queue — an empty
queue costs one indexed query and returns, which is cheaper and far harder to
get wrong than routing wake-ups by channel — but each queue owns its own
`asyncio.Event`, because `_wait_for_wake_or_tick` consumes what it waited on
and one shared event between two consumers is a lost wake-up. Every wake fans
out to that queue's `concurrency` drainers, each on its own session, so one
hanging call stalls one drainer instead of the queue —
`FOR UPDATE SKIP LOCKED` keeps their claims disjoint without any coordination.

The rows in those tables are the queues themselves — this process holds no
state worth preserving and can be killed at any moment. On SIGTERM a loop
caught mid-drain gets `SHUTDOWN_DRAIN_SECONDS` to finish its batch and is
otherwise cancelled, which rolls that batch back and returns its rows to
`pending`.

`Queue` (name, channel, drain, concurrency) is what makes all of that
parameterised rather than duplicated; a third queue is a fourth entry in
`_queues()`, and its channel constant must be imported from the module that
NOTIFYs it, never respelled here.

## Run locally

```bash
make dev-worker
```
