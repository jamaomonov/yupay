# Runbook — Waxpeer (Steam wallet top-ups)

Waxpeer sells one thing to us: crediting a customer's Steam wallet by a
dollar amount they chose at checkout. See [ADR-0032](../decisions/0032-variable-amount-skus.md)
for why the amount lives on the order line and why refunds on this supplier
are manual.

## Symptoms → diagnosis

| Symptom (admin sees)                                                         | Likely cause                                                                    | First action                                                                                        |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Steam orders stuck `in_progress` + «Низкий баланс поставщика» ops alert      | Our Waxpeer wallet is too low to fund the top-ups                               | See "Low balance (soft failure at fulfilment)" below — top up + Retry                               |
| Checkout fails with "Цена временно недоступна" for the Steam product         | FX trust gate rejected the USD rate                                             | See "Price unavailable (FX trust gate)" below                                                       |
| Task stuck `in_progress`, Waxpeer status `created`/`sending` for a long time | Waxpeer has no webhook — the sweep hasn't caught it yet                         | Wait up to 60s for the next sweep tick, or query Waxpeer directly (see "Inspecting a stuck top-up") |
| Task `failed`, `last_error` mentions "refunded"                              | Waxpeer `canceled` the top-up                                                   | No action needed on the supplier side — the balance is already back on our Waxpeer wallet           |
| Task `failed`, `last_error` mentions "needs manual reconciliation"           | Waxpeer `error` — it did **not** refund us                                      | See "The `error` case — manual reconciliation needed" below                                         |
| `waxpeer.give_amount_short` in the logs                                      | Waxpeer started charging a fee we haven't configured                            | See "`give_amount` shortfall" below                                                                 |
| `waxpeer_reconcile.page_limit_hit` in the scheduler logs                     | Backlog of in-flight top-ups larger than the sweep can page through in one tick | See "Reconciliation sweep" below                                                                    |

## Inspecting a stuck top-up

Every Waxpeer top-up is one `FulfillmentTask` (one per `OrderItem`). The
`custom_id` we send Waxpeer **is** the task's own id
(`idempotency_key=task.id` in `fulfillment/service.py`), and
`task.external_order_id` is set to the same value once `fulfill()` returns —
so the task id is always the key to query Waxpeer with.

1. Find the task from our side:

   ```
   GET /api/v1/admin/fulfillment/tasks?order_id=<order_id>
   GET /api/v1/admin/fulfillment/tasks/{task_id}
   ```

   `status` and `last_error` are always reliable — those fields get written
   regardless of whether the task resolved inline (`fulfill()`) or through
   the reconciliation sweep (`check_status()`, the common case — see
   "Reconciliation sweep" below). `extra_metadata` (`waxpeer_status`,
   `amount_units`, `give_amount_units`, and — only when relevant —
   `supplier_refunded` / `needs_reconciliation` / `give_amount_shortfall_units`)
   is only populated when the task resolved inline through `fulfill()`; a
   task the sweep resolves instead will not have these fields even though
   the outcome they describe did happen. See "Known limitation" under "The
   `error` case" below. This is also the Fulfilment Inbox's data — the
   "Failed" tab shows the same tasks once they leave `in_progress`.

2. Cross-check against Waxpeer directly. Our own `extra_metadata` does
   **not** carry Waxpeer's numeric top-up id (their "pay id") for a failed
   task — only a `succeeded` task's delivery artifact has it. To get the pay
   id, or to see what Waxpeer's side currently says regardless of what our
   DB has, query their API with the task id as `custom_id`:

   ```bash
   curl "https://api.waxpeer.com/v1/steam-topup?custom_id=<task_id>&api=$WAXPEER_API_KEY"
   ```

   The response's `topup.id` is the pay id — that's what to hand to Waxpeer
   support. You can also look up by that id directly with `?id=<pay_id>`
   instead of `?custom_id=`.

## What each status means for the customer's money

| Waxpeer `status`                       | Our outcome   | Customer's money                                                                                                                                                                                                                   |
| -------------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `created` / `sending`                  | `in_progress` | Charged, in flight. Nothing to do — wait for the sweep or Waxpeer to settle.                                                                                                                                                       |
| `completed`                            | `succeeded`   | Delivered to the Steam wallet. Done.                                                                                                                                                                                               |
| `canceled`                             | `failed`      | Waxpeer **refunded our Waxpeer balance**. Refund the customer as usual.                                                                                                                                                            |
| `error`                                | `failed`      | Waxpeer did **not** refund us. See below — needs manual reconciliation.                                                                                                                                                            |
| `unknown` (unrecognised status string) | `in_progress` | Treated as still in flight on purpose — see the module docstring in `waxpeer.py`: reading an unrecognised value as success or failure risks marking undelivered goods delivered, or refunding money that later completes normally. |

## The `error` case — manual reconciliation needed

Waxpeer's `error` status means the top-up failed in a way it does not
auto-refund. This is the one supplier failure mode in this codebase where
our money and the customer's order genuinely disagree until a human steps
in — there is deliberately no auto-refund (see ADR-0032: refunds here are
always whole-order, admin-triggered, same as every other supplier).

**Where to find these tasks:** the task is `failed`, and its `last_error`
reads "waxpeer reported an error on this top-up; it does not auto-refund
this case — needs manual reconciliation". That text is what actually
surfaces the task in the Fulfilment Inbox's "Failed" tab — filter/search on
it (or on `supplier=waxpeer, status=failed` and eyeball it) to find every
top-up that needs this treatment.

1. **Refund the customer** the normal way, from the Fulfilment Inbox / the
   order: `POST /api/v1/admin/payments/{payment_id}/refund` with an
   `Idempotency-Key` header. This is identical to refunding any other failed
   supplier task — nothing Waxpeer-specific about this step.
2. **Recover our side separately.** The customer refund does not get our
   Waxpeer balance back — Waxpeer kept that money. Look up the pay id (see
   "Inspecting a stuck top-up" above) and open a support ticket with Waxpeer
   referencing it. This is a manual, out-of-band step; there is no API call
   in this codebase that automates it.

Do not retry an `error` task expecting a different outcome — Waxpeer already
gave a terminal answer for that `custom_id`; a repeat `fulfill()` call
returns the same top-up (idempotent replay) rather than trying again.

**Known limitation — `extra_metadata` is not a reliable signal here.**
`WaxpeerFulfiller` also builds an `extra_metadata.needs_reconciliation =
true` flag (and, for the `canceled` case, `supplier_refunded = true`), but
`FulfillStatus` (the return type of `Fulfiller.check_status`, in
`fulfillment/suppliers/base.py`) has no `extra_metadata` field — only
`FulfillResult` (the synchronous `fulfill()` return type) does. Both the
reconciliation sweep and a real webhook go through
`fulfillment.process_webhook_update`, which calls `check_status()` and
never writes `task.extra_metadata`. Because Waxpeer has no webhook, nearly
every top-up's terminal outcome is discovered through this path rather than
`fulfill()`'s inline result, so these flags are not a queryable structured
field in production — `last_error` (for `error`/`canceled`) and the
`waxpeer.give_amount_short` log line (for a fee shortfall — see below) are
the reliable signals. This is a known gap, not a design choice; giving
`FulfillStatus` a metadata slot (and having `process_webhook_update`
persist it) is a follow-up, not implemented here.

## Price unavailable (FX trust gate)

Steam top-up pricing goes through `pricing.fx_guard` before it can be shown
or charged (ADR-0032). If `fx`'s entire provider chain is down, or the
USD→currency rate fails any of the gate's four further checks (non-positive,
older than `pricing_fx_max_age_seconds`, deviated more than
`pricing_fx_max_deviation_pct` from the last known-good rate, or outside
`pricing_fx_min_rate_uzs`…`pricing_fx_max_rate_uzs`), the SKU's
storefront price disappears (falls back to no price shown, never the raw
market rate) and checkout for it fails with 502
`UpstreamUnavailableError` ("Цена временно недоступна. Попробуйте позже.").
This is not Waxpeer-specific — it would fire for any variable-amount SKU —
but Steam top-up is the only one live today.

1. Grep the logs for `pricing.rate_rejected` — it carries the `reason`
   (`unavailable` / `non_positive` / `stale` / `deviation` / `out_of_band`)
   and the quote currency.
2. If the reason is `unavailable`, that's the direct signal: `fx`'s entire
   provider chain returned nothing (`FxUnavailableError`) — a total FX
   outage, not a bad-but-present rate. Don't wait for a `stale` log line to
   notice this; `unavailable` fires immediately, before `check_rate` even
   runs. Check the `fx` module's provider health directly.
3. If the reason is `stale`, check whether the `fx` module's provider chain
   is actually failing (its own health, not this gate's) — the trust gate
   only judges the freshest rate `fx` handed it, it does not fetch rates
   itself.
4. If the reason is `deviation` or `out_of_band` during a genuine, large,
   real-world FX move (not a bad provider read), the current
   `pricing_fx_max_deviation_pct` / `pricing_fx_min_rate_uzs` /
   `pricing_fx_max_rate_uzs` settings may need a deliberate one-off bump —
   treat that as a judgement call, not a routine fix, since these bounds
   exist specifically to stop a bad rate from reaching a customer.
5. See `apps/api/src/yupay/modules/pricing/README.md` for the full
   check order and current setting defaults.

## Low balance (soft failure at fulfilment)

A low Waxpeer balance never blocks checkout — the same as G2B. The order is
accepted and paid; if our Waxpeer wallet can't fund the top-up, Waxpeer refuses
the `POST /steam-topup` with "not enough balance", and `WaxpeerFulfiller.fulfill`
returns the soft `supplier_low_balance` sentinel instead of a hard error. The
saga (`fulfillment.service.process_task`) then:

- marks the fulfilment **task** `failed` (it lands in the Fulfilment Inbox), but
- keeps the order **item** `in_progress`, so the customer keeps seeing
  «в обработке» rather than an error, and
- fires an ops Telegram alert («⚠️ Низкий баланс поставщика», deduped per
  supplier in Redis for a window) carrying the amount required and the current
  balance.

**Recovery:** top up the Waxpeer wallet through Waxpeer's own dashboard/support
(no automated top-up — see the design spec's "Out of scope"), then hit **Retry**
on the task in the Fulfilment Inbox (`POST /admin/fulfillment/tasks/{id}/retry`),
or fulfil the order manually. A retry re-runs `fulfill` with the same
`custom_id`; because the low-balance refusal created nothing on Waxpeer's side,
the retry is a fresh top-up, not a stale replay. Because the customer stayed on
«в обработке» the whole time, this is invisible to them as long as you top up
before they give up.

**Working a backlog:** the Fulfilment Inbox's operator tabs — "Failed",
"Висяки" (stuck), and the manual queue — fetch tasks **oldest-first**
(`GET /admin/fulfillment/tasks?…&order=oldest`) and cap the window at 200. So
after a balance outage that parked many top-ups, the longest-waiting customer's
task is at the top, and if more than 200 piled up, the newest fall off the end,
never the most overdue. Clear from the top down. (The "Все" browse tab is the
opposite — newest-first, `order=newest`, the default — because there you want
recent activity on page one, not ancient history.)

There is also no admin health/balance page for Waxpeer yet (G2B has
`/admin/integrations/g2b/health`; Waxpeer doesn't). Check the balance
directly:

```bash
curl "https://api.waxpeer.com/v1/user?api=$WAXPEER_API_KEY"
# → {"success": true, "user": {"wallet": <units>, ...}} — 1000 units = $1
```

If checkout is failing for every Steam top-up and the balance above is low,
top up the Waxpeer account balance through Waxpeer's own dashboard/support
(this codebase has no automated top-up path — see the design spec's "Out of
scope"), then confirm with the same `curl` call before telling anyone
checkout is fixed.

An empty `WAXPEER_API_KEY` produces the same customer-facing failure via a
different path (`WaxpeerFulfiller.available` is `False`) — check
`secrets/api.env` first if the balance call above returns 401/403 instead of
a wallet figure.

## `give_amount` shortfall

Waxpeer's `amount` (what we're charged) and `give_amount` (what actually
lands in the Steam wallet) are supposed to match today — Waxpeer's fee is
0%. `WaxpeerFulfiller` reconciles the two after every `fulfill()`/
`check_status()` call: if `give_amount` comes in short of what we promised
the customer, it logs

```
waxpeer.give_amount_short  order_item_id=... promised_units=... give_amount_units=...
```

at error level, unconditionally, from both code paths — **this log line is
the reliable signal to grep for**, not a task field. `WaxpeerFulfiller` also
builds a `give_amount_shortfall_units` entry for the task's
`extra_metadata`, but that only reaches the DB when the task resolves
inline through `fulfill()`; the far more common path — `check_status()`,
driven by the reconciliation sweep, since Waxpeer has no webhook — returns
a `FulfillStatus` with no metadata slot to carry it (see "Known limitation"
under "The `error` case" above). The top-up is still marked delivered
either way (the money already moved) — the shortfall is just made visible
via the log line instead of silently swallowed.

**If you see this log line, Waxpeer has started charging a fee.** Fix:

1. Compute the fee rate from the shortfall (`shortfall_units /
promised_units`, roughly).
2. Set `WAXPEER_FEE_RATE=<rate>` (a decimal in `[0, 1)`, e.g. `0.05` for 5%)
   in `secrets/api.env`.
3. Redeploy:

   ```bash
   docker compose up -d --force-recreate api worker scheduler
   ```

Once set, `pricing.variable.to_units` grosses the request up by that fee so
the customer still receives exactly the amount they paid for — see
`apps/api/src/yupay/modules/pricing/README.md`.

## Reconciliation sweep

Waxpeer has no webhook. `apps/scheduler/src/yupay_scheduler/jobs/
waxpeer_reconcile.py` runs every 60 seconds, lists every `in_progress`
waxpeer task, and drives each one to a terminal state through the same
`fulfillment.process_webhook_update` a real webhook would call. Each task is
reconciled in its own transaction, so one bad row (a transient DB hiccup, a
surprising Waxpeer response) never blocks the rest of the backlog.

- **`waxpeer_reconcile.page_limit_hit`** — the sweep paginates in batches of
  100 tasks, up to 50 pages (5,000 tasks) per tick. Seeing this means the
  `in_progress` backlog is bigger than that ceiling — investigate why so
  many top-ups are stuck rather than assuming the sweep will "catch up next
  tick" (it re-pages from the start every tick).
- **Known limitation:** the sweep orders tasks by `created_at desc` (newest
  first — it's `list_tasks_admin`'s default ordering, unchanged for this
  job), so a large backlog is worked newest-stuck-first, not oldest-first.
  The oldest stuck top-up can wait behind a large batch of newer ones until
  the backlog drains. This hasn't mattered at normal volume; if a real
  backlog ever forms, oldest-first would be a one-line change to the
  `list_tasks_admin` call in `_list_stuck_task_ids`.
- The sweep is safe to run concurrently with itself
  (`max_instances=1` in APScheduler, plus `process_webhook_update` no-ops on
  a task that's already terminal) — you don't need to worry about triggering
  a double-reconcile by waiting out two ticks.

## Related

- ADR-0032 — variable-amount SKUs, the FX trust gate, and why refunds here
  are manual.
- `apps/api/src/yupay/modules/pricing/README.md` — amount→units,
  amount→price, the FX trust gate and its settings.
- `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer.py`,
  `waxpeer_client.py` — the adapter and transport this runbook describes.
- `apps/scheduler/src/yupay_scheduler/jobs/waxpeer_reconcile.py` — the sweep.
- `docs/runbooks/g2b-troubleshooting.md` — the equivalent runbook for G2B;
  read it too if you're new to the Fulfilment Inbox in general.
