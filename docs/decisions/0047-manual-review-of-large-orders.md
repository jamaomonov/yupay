# 0047. Hold large orders for manual review

- **Status**: Accepted
- **Date**: 2026-08-09
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security

## Context and problem statement

Order creation had no limit of any kind. Anything paid was fulfilled
automatically within minutes, and fulfilment is irreversible — an issued code or
a credited game balance cannot be taken back.

Production numbers as of 2026-08-09, over 26 paid orders in 13 active days:
median 14 246 UZS (~$1), 90th percentile 149 631 UZS (~$11), maximum
2 787 780 UZS (~$202). The maximum is **18× the 90th percentile**, and it is
also the order the operator believes was placed to launder money. Before it, the
same account had placed one order for exactly $1 two hours earlier — test small,
then go large, which is the shape this rule is aimed at.

26 orders is not a sample. Nothing here is derived statistically; the threshold
is a judgement about where outliers begin, made explicit so it can be moved.

## Decision drivers

- The loss on a fraudulent order is not the margin, it is the whole amount plus
  the wholesale cost already paid to the supplier, plus (per
  [ADR-0044](./0044-chargeback-evidence-capture.md)) whatever the acquirer
  withholds from later payouts.
- A control that also stops ordinary sales is an outage, not a control. At a
  median of $1, a threshold in the tens of dollars touches almost nothing.
- Holding is reversible in one click; delivering is not. When one direction is
  cheap to undo and the other is not, the default belongs on the cheap side.

## Considered options

1. **Block the order before payment** — refuse to accept money above a limit.
2. **Deliver, then review** — fulfil as now and look at large orders afterwards.
3. **Take payment, hold delivery** for review.

## Decision outcome

**Chosen option: 3.**

Option 1 loses legitimate large sales outright and gives the customer nothing to
wait for. Option 2 reviews a decision that has already been executed, which is
not a review.

- `orders.risk.review_reason(order)` returns a reason string or `None`. It lives
  outside both `payments` and `fulfillment` because the decision is neither about
  taking money nor about delivering goods, and the next rule (velocity, repeat
  cards, small-then-large from one account) should land somewhere obvious rather
  than wherever was convenient.
- The check sits at the single point where a settled payment starts the saga
  (`payments.service`, ADR-0013). If it fires, `start_for_order` is simply not
  called.
- **The order stays `paid`.** No new status, so the storefront, the mini app and
  the FSM learn nothing new, and the customer sees "processing" — which is what
  it honestly is. The hold is the _absence_ of a call, not a state to reverse:
  releasing it is `POST /admin/fulfillment/orders/{id}/release`, the same
  idempotent `start_for_order` the webhook skipped.
- The operator reaches that release from the order page itself: a held order is
  invisible on the Fulfilment screen (it has no task to list) and reads as an
  ordinary `paid` order everywhere else, so the order detail page keys a banner
  off the `order.held_for_review` event and puts the release behind a confirm.
  Without it the alert names an order the admin panel offers no way to act on.
- Threshold is **$40** by default, denominated in USD against `orders.total_usd`
  because the som figure moves with the rate. `0` disables the rule without a
  deploy. Comparison is `>=`: setting the limit to 40 means 40 is big enough to
  look at.
- Holding pre-arms the stuck-order watchdog's Redis key
  ([ADR-0046](./0046-stuck-paid-order-watchdog.md)) so its first reminder lands
  one repeat window out instead of 15 minutes out. Otherwise a held order
  produces two alerts within the quarter hour, and a channel that repeats itself
  stops being read.

## Negative consequences

- A legitimate large buyer waits for a human. At current volume that is roughly
  one order in twenty-six; at ten times the volume it is a support burden that
  will need either a higher threshold or per-customer trust.
- The threshold lives in the environment, so changing it needs a deploy. Moving
  it into the admin panel needs a settings store that does not exist yet —
  deferred deliberately rather than built on a guess about how often it changes.
- The rule only knows the amount. The $1-then-$202 pattern that actually
  characterised the suspicious account is invisible to it; catching that needs
  velocity rules over the evidence ADR-0044 started collecting.

## Validation

Unit tests pin the boundary (`>=`, and `0` disabling). Integration tests pay a
real order through the real webhook and assert the negative that matters — no
fulfillment task, no `order.fulfilling` event, order still `paid` — then that
release creates the withheld work, and that an order below the threshold is
untouched.

## References

- [ADR-0013](./0013-fulfillment-skeleton-and-provider-stubs.md) — the post-payment saga this gates
- [ADR-0046](./0046-stuck-paid-order-watchdog.md) — the reminder loop a held
  order joins
- [ADR-0044](./0044-chargeback-evidence-capture.md) — what a fraudulent order
  costs, and the capture a future velocity rule will read
