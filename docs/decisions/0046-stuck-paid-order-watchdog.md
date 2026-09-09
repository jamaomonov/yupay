# 0046. Watchdog for orders paid but never delivered

- **Status**: Accepted
- **Date**: 2026-08-09
- **Deciders**: @jamaomonov
- **Tags**: backend | observability | payments

## Context and problem statement

On 2026-08-07 at 13:46 UTC the largest order the platform had ever taken —
2 787 780 UZS (~$202), against a median order of 14 246 UZS — was paid through
Click. Two seconds later the Waxpeer call failed with `supplier_low_balance`.
Per [ADR-0040](./0040-order-realtime-ws.md) a fulfillment failure is not an order
failure, so the order correctly stayed at `fulfilling` for an operator to
resolve rather than showing the customer an error.

No operator resolved it. The order sat undelivered for a day: our money, the
customer's goods, and nothing asking about it.

The existing `_maybe_alert_low_balance` **did fire** and the ops Telegram message
**was delivered** — confirmed with the operator. That is the important part of
the diagnosis: the alerting channel worked exactly as designed. It fired once,
de-duplicated for 15 minutes, and then went quiet forever while the order stayed
stuck. One message, arriving mid-day, was all the system ever said.

A second production order (2026-07-23, 1 000 UZS) had been sitting paid and
undelivered for over two weeks with **no fulfillment task at all** — so nothing
downstream of the task table could have noticed it either.

## Decision drivers

- A single notification is indistinguishable from no notification once it has
  scrolled out of view. Ops attention is not a queue that guarantees delivery.
- Whatever the cause, "we took the money and delivered nothing" is one condition
  with one remedy path, and it is the condition worth watching.
- An alert nobody can verify after the fact is a liability during an incident:
  we could not tell from logs whether the alert had been sent, because success
  was not logged and the not-configured branch logged at DEBUG, which prod
  discards at `LOG_LEVEL=INFO`.

## Considered options

1. **Widen the low-balance alert** — shorten the dedupe window, alert harder on
   supplier failures.
2. **Watch the fulfillment task table** for tasks in `failed` past some age.
3. **Watch the order** — anything paid and undelivered past a threshold, whatever
   the downstream state.

## Decision outcome

**Chosen option: 3**, with the logging gap fixed alongside.

Option 1 treats the symptom that happened to occur first; a supplier timeout, a
crashed worker, or a task that was never created produce the same customer-facing
outcome and would each need their own alert. Option 2 is what an engineer
naturally reaches for and is exactly what would have missed the 2026-07-23 order,
which had no task row to find.

- `orders.service.list_stuck_paid_orders` selects on the order: status in
  `paid`/`fulfilling`/`fulfilled`, `delivered_at IS NULL`, paid longer ago than
  the threshold. Oldest first — the longest-waiting customer is the nearest to
  filing a dispute.
- A scheduler job runs every 5 minutes. Threshold defaults to **15 minutes**
  (normal delivery is 1–5, so this clears the happy path without training the
  operator to ignore the channel) and **re-alerts every 4 hours** while the order
  stays unresolved. The repeat is the actual fix; the detection already existed.
- Per-order rate limiting via Redis `SET NX`, and it **fails open**: if Redis is
  unreachable, a duplicate alert is a better failure than silence about money we
  are holding.
- `send_admin_alert` now logs every outcome at INFO, including success, and takes
  a `kind` label. Without this, "no alert arrived" and "no alert was sent" look
  identical in hindsight — which is precisely the question this incident raised.
- The tick logs `stuck=N alerted=M` even when M is 0, so a quiet Telegram during
  a live incident has a corresponding line explaining why.

### Deliberately not done

- **No auto-refund and no auto-retry.** Both spend money or contact a supplier
  without a human, and the correct remedy differs per case (top up and retry,
  fulfil manually, refund). The alert says which options exist and stops there.
- **No customer-facing change.** ADR-0040's rule stands: a paid order does not
  flip to a customer-visible failure. This is an ops watchdog, not a status.

### Amended 2026-09-09 (M3c Task 6): one shape leaves this query by moving

A **merchant** order whose whole deposit charge is refunded automatically is now
closed as `failed` by the fulfilment seam ([ADR-0071](./0071-merchant-refunds.md),
decision 12), so it stops matching `STUCK_STATUSES` and this watchdog stops
alerting about it. That is the intended reading of this ADR, not an exception to
it: the money is back, so there is nothing an operator can do and nothing worth
shouting about — the same reason `refunded` is already excluded.

The query was **not** changed. An earlier plan proposed gating the job on
`merchant_id`; the state was wrong rather than the alert, and a watchdog that
knows about resellers would have been a second place to keep that knowledge
correct. ADR-0040's rule is intact for retail and for any merchant order whose
money did not come back: those still leave the order at `fulfilling` and still
appear here.

## Negative consequences

- A supplier outage affecting many orders produces one alert per order. At
  current volume (65 orders in 13 days) that is fine; if it becomes noise the
  fix is to group by cause, not to lengthen the repeat window.
- The watchdog only knows what the order table knows. An order marked delivered
  whose goods never actually reached the player is invisible to it.

## Validation

Integration tests assert the two production shapes it must never miss: a paid
order with no fulfillment task at all, and one whose supplier call failed. Plus
the negatives — inside the delivery window, delivered, expired, refunded — since
a watchdog that cries about resolved orders gets muted, and a muted watchdog is
where this ADR started.

## References

- [ADR-0040](./0040-order-realtime-ws.md) — why a fulfillment failure leaves the
  order at `fulfilling` and awaits an operator, the rule this watchdog backstops
- [ADR-0044](./0044-chargeback-evidence-capture.md) — the dispute this prevents:
  an undelivered paid order is a chargeback we would deserve and could not defend
