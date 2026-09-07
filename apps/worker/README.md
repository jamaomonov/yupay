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
state worth preserving and can be killed at any moment.

**A queue loop that dies takes the process with it.** `run()` supervises the
loop tasks: one that raises (or returns without a stop signal) is logged as
`worker.consumer.queue_loop_died` and `run()` exits **1**, so
`restart: unless-stopped` restarts the container. Without that, decoupling the
queues would have removed the crash that used to make a dead queue visible —
the process would stay up, healthy-looking and one queue short, with all
fulfilment stopped and `worker.consumer.started` still standing.

**Shutdown is one budget, not two.** `SHUTDOWN_BUDGET_SECONDS` (8) covers the
whole path from the stop signal to the last log line; a loop caught mid-drain
gets the first `SHUTDOWN_DRAIN_SECONDS` (3) of it and the fire-and-forget
notification sends get whatever is left. Cancelling a drain is safe — it rolls
the batch back and its rows return to `pending` — while a cancelled Telegram
send is a customer who is never told their order is ready, which is why the
remainder goes to the sends. 8 and not 10 because Docker's default
`stop_grace_period` is 10 s and neither compose file overrides it for `worker`;
raising the budget past that means setting `stop_grace_period` first.

`Queue` (name, channel, drain, concurrency) is what makes all of that
parameterised rather than duplicated; a third queue is a fourth entry in
`_queues()`, and its channel constant must be imported from the module that
NOTIFYs it, never respelled here.

## Run locally

```bash
make dev-worker
```
