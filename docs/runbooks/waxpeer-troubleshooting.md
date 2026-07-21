# Runbook — Waxpeer (Steam wallet top-ups)

Waxpeer sells one thing to us: crediting a customer's Steam wallet by a
dollar amount they chose at checkout. See [ADR-0032](../decisions/0032-variable-amount-skus.md)
for why the amount lives on the order line and why refunds on this supplier
are manual.

## Symptoms → diagnosis

| Symptom (admin sees)                                                         | Likely cause                                                                    | First action                                                                                        |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Checkout fails with "Пополнение временно недоступно" for every Steam top-up  | `WAXPEER_API_KEY` empty or our Waxpeer balance too low                          | See "Low-balance preflight" below                                                                   |
| Checkout fails with "Цена временно недоступна" for the Steam product         | FX trust gate rejected the USD rate                                             | See "Price unavailable (FX trust gate)" below                                                       |
| Task stuck `in_progress`, Waxpeer status `created`/`sending` for a long time | Waxpeer has no webhook — the sweep hasn't caught it yet                         | Wait up to 60s for the next sweep tick, or query Waxpeer directly (see "Inspecting a stuck top-up") |
| Task `failed`, `last_error` mentions "refunded"                              | Waxpeer `canceled` the top-up                                                   | No action needed on the supplier side — the balance is already back on our Waxpeer wallet           |
| Task `failed`, `extra_metadata.needs_reconciliation = true`                  | Waxpeer `error` — it did **not** refund us                                      | See "`needs_reconciliation` — the `error` case" below                                               |
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

   The `status`, `last_error`, and `extra_metadata` (`waxpeer_status`,
   `amount_units`, `give_amount_units`, and — only when relevant —
   `supplier_refunded` / `needs_reconciliation` / `give_amount_shortfall_units`)
   are all there. This is also the Fulfilment Inbox's data — the "Failed"
   tab shows the same tasks once they leave `in_progress`.

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

## `needs_reconciliation` — the `error` case

Waxpeer's `error` status means the top-up failed in a way it does not
auto-refund. This is the one supplier failure mode in this codebase where
our money and the customer's order genuinely disagree until a human steps
in — there is deliberately no auto-refund (see ADR-0032: refunds here are
always whole-order, admin-triggered, same as every other supplier).

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

## Price unavailable (FX trust gate)

Steam top-up pricing goes through `pricing.fx_guard` before it can be shown
or charged (ADR-0032). If the USD→currency rate fails any of the gate's four
checks (non-positive, older than `pricing_fx_max_age_seconds`, deviated more
than `pricing_fx_max_deviation_pct` from the last known-good rate, or
outside `pricing_fx_min_rate_uzs`…`pricing_fx_max_rate_uzs`), the SKU's
storefront price disappears (falls back to no price shown, never the raw
market rate) and checkout for it fails with 502
`UpstreamUnavailableError` ("Цена временно недоступна. Попробуйте позже.").
This is not Waxpeer-specific — it would fire for any variable-amount SKU —
but Steam top-up is the only one live today.

1. Grep the logs for `pricing.rate_rejected` — it carries the `reason`
   (`non_positive` / `stale` / `deviation` / `out_of_band`) and the quote
   currency.
2. If the reason is `stale`, check whether the `fx` module's provider chain
   is actually failing (its own health, not this gate's) — the trust gate
   only judges the freshest rate `fx` handed it, it does not fetch rates
   itself.
3. If the reason is `deviation` or `out_of_band` during a genuine, large,
   real-world FX move (not a bad provider read), the current
   `pricing_fx_max_deviation_pct` / `pricing_fx_min_rate_uzs` /
   `pricing_fx_max_rate_uzs` settings may need a deliberate one-off bump —
   treat that as a judgement call, not a routine fix, since these bounds
   exist specifically to stop a bad rate from reaching a customer.
4. See `apps/api/src/yupay/modules/pricing/README.md` for the full
   check order and current setting defaults.

## Low-balance preflight

Unlike G2B, a low Waxpeer balance is caught **before** the order is created,
not after. `orders.service._preflight_variable_supplier_balance` calls
`WaxpeerFulfiller.has_balance()` (`GET /v1/user`, comparing `user.wallet`
against the grossed-up amount) while building the order; if it's short, the
whole checkout fails with a generic "Пополнение временно недоступно.
Попробуйте позже." (`UpstreamUnavailableError`, HTTP 502) and **no order is
created**. There is no `supplier_low_balance` fulfilment task to retry for
this supplier the way there is for G2B — nothing lands in the Fulfilment
Inbox, because nothing was ever charged.

**Edge case:** the preflight and the actual `fulfill()` call are two
separate Waxpeer requests, so a balance drained in between (e.g. two orders
racing the same low balance) can still make `POST /steam-topup` itself
refuse for lack of funds. That refusal is **not** recognised as the
`supplier_low_balance` sentinel G2B uses — it surfaces as a generic failed
task (`last_error` like `"waxpeer top-up failed: HTTP 200"`) and the order
item flips straight to `failed` instead of the softer "stays in_progress,
alert admin" handling G2B gets. Treat any Waxpeer task failing right after a
`GET /v1/user` shows a healthy balance as this race, not a real bug, and
retry once the balance is topped up.

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

at error level and records `give_amount_shortfall_units` on the task's
`extra_metadata` — the top-up is still marked delivered (the money already
moved), the shortfall is just made visible instead of silently swallowed.

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
