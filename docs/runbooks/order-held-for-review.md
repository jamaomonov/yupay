# Runbook — an order held for review

The order risk gate (`orders/risk.py`, ADR-0047 + ADR-0062) holds a paid
order before fulfilment starts instead of blocking the payment. The order
stays in status `paid` — nothing new for the customer to see, they get
"processing," which is honestly what it is — and no fulfilment task is
created, so a held order is invisible on the Fulfilment screen and looks like
an ordinary just-paid order everywhere except the order detail page, which
keys a warning banner off the `order.held_for_review` event.

**The gate never blocks a sale.** By the time any rule below runs, the money
is already taken. The only open question is whether a human looks before an
irreversible good (a code, a game-account credit) leaves.

## The alert

A held order pages the admin Telegram channel (`kind="order_held_for_review"`),
one message per hold, e.g.:

> 🔍 Крупный заказ — на проверке
> Заказ: `a1b2c3d4…`
> Сумма: **550 000 UZS** ($40.12)
> _Оплачен, выдача НЕ запущена. Проверь плательщика, затем выдай или верни деньги._

The alert deliberately carries **no IP, device, email, or other identity** —
`hold_for_review`'s payload and the alert text only ever contain the reason
and counts (see ADR-0044/§9 on why raw identity data doesn't get copied
around). Finding the rest of a linked group is a step you do in the admin
panel, described below.

## The six reasons

| Reason (`order_events.payload.reason`)                        | Fires when                                                                                                                                                                                                                                                                                                                                                                                                                          | Detail                                                                                                                                                                  |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `amount_at_or_above_threshold` (`REASON_LARGE_AMOUNT`)        | This order's `total_usd` is at or above the effective threshold. Threshold is jittered per order id within `[0.6, 1.0) × MANUAL_REVIEW_THRESHOLD_USD` so probing for the edge finds a band, not a line — the same order always gets the same effective threshold, but two different orders at the same nominal amount can land on either side of it.                                                                                | ADR-0047                                                                                                                                                                |
| `paid_after_order_expired` (`REASON_PAID_AFTER_EXPIRY`)       | The acquirer settled the payment after the order had already been marked `expired`. The sale is real, but it was priced and stocked ten minutes ago.                                                                                                                                                                                                                                                                                | [paid-after-expiry.md](./paid-after-expiry.md) has the full procedure — different for wallet top-ups vs. catalog orders, and for timeout vs. operator-cancelled orders. |
| `identity_rolling_sum_exceeded` (`REASON_ROLLING_SUM`)        | Orders sharing an identity (buyer, IP, device, or delivery target) sum to `RISK_SUM_24H_USD` or more within 24h, or `RISK_SUM_7D_USD` or more within 7 days — many small orders instead of one large one.                                                                                                                                                                                                                           | ADR-0062                                                                                                                                                                |
| `identity_velocity_exceeded` (`REASON_VELOCITY`)              | `RISK_VELOCITY_24H` or more paid orders sharing an identity within 24h, regardless of amount — a burst of cheap orders is itself a signal.                                                                                                                                                                                                                                                                                          | ADR-0062                                                                                                                                                                |
| `identity_shared_across_buyers` (`REASON_SHARED_IDENTITY`)    | This order's IP or device was used by `RISK_DISTINCT_BUYERS_7D` or more distinct buyer identities within 7 days. Matched on IP/device only, not buyer or delivery target, because a resale ring's whole method is rotating the buyer identity (and often the delivery target) on every order.                                                                                                                                       | ADR-0062                                                                                                                                                                |
| `guest_liquid_brand_foreign_timezone` (`REASON_GEO_MISMATCH`) | A **guest** order touches a brand in `RISK_LIQUID_BRANDS` (cash-equivalent goods like Roblox or Telegram Stars) and the browser's reported timezone is outside `RISK_HOME_TIMEZONES`. Weak evidence alone — a travelling customer is not a fraudster — which is why it only fires alongside the other two conditions, and never for a signed-in buyer (an account with order history is already covered by the window rules above). | ADR-0062                                                                                                                                                                |

Rules run in this order — amount, rolling sum, velocity, shared identity,
geo — and the first hit wins; only one reason is ever recorded per order.

## Finding the linked group

The banner on the order detail page shows the reason for _this_ order only.
For the four window rules, the point is not this order — it's the group.
**Releasing one order out of a linked group without checking the rest
defeats the rule**: if the pattern held, the rest of the group is still
sitting there.

1. **Buyer-linked groups** (rolling sum or velocity keyed on `buyer`, or
   shared-identity's own buyer list): open the admin orders list and search
   (`q=`) by the buyer's email or user id. The search matches a guest email
   substring or a full user id — see `orders.service._admin_search_clause`.
2. **IP/device-linked groups** (shared identity, or rolling
   sum/velocity keyed on IP or device rather than buyer): the admin orders
   list has **no search by IP or device today** — `q` only matches an order
   id, user id, or guest email. Open the held order's evidence pack
   (`GET /admin/orders/{id}/evidence`, admin-only) to read the raw IP, then
   scan recent orders around the same time window for a match. (The pack
   currently exposes `ip`, not `device_hash` — device-only matches need a
   database lookup; ask an engineer if none of the orders share an IP.)
3. **Delivery-target-linked groups** (a Roblox username or Stars `@handle`
   receiving from several orders): not searchable from the admin UI at all
   today; a database lookup on `order_items.fulfillment_data` is the only
   way to enumerate them.

Once you have the group: check each order's status, decide release-or-refund
per order (not once for the whole group), and only release the ones you're
satisfied with individually.

## Release vs. refund

- **Release** — `POST /admin/fulfillment/orders/{id}/release` (the "Выдать"
  button on the order page). This is **the same call**
  `fulfillment.start_for_order` would have made at payment time; there is no
  separate "held" state to undo. It's idempotent, so a double click can't
  deliver twice. Not offered for `purpose == "wallet_topup"` orders — see
  below.
- **Refund** — `POST /admin/payments/{id}/refund` from the payments block on
  the order page. Full procedure, including the wallet-funded case:
  [wallet-refunds.md](./wallet-refunds.md).
- **Wallet top-ups**: the risk gate never holds a wallet top-up in the first
  place (the call site skips the gate — a wallet credit is reversible, the
  irreversible-goods risk this gate exists for doesn't apply). If you land
  here from a _different_ hold (`paid_after_order_expired` on a top-up),
  follow [paid-after-expiry.md](./paid-after-expiry.md) instead — crediting a
  held top-up is a manual wallet adjustment, not a release.

The order detail banner's explanatory text does not yet distinguish between
the five reasons other than `paid_after_order_expired` — it shows one
generic "amount above threshold" message regardless of which window rule
actually fired. Trust the `reason` field in the `order.held_for_review`
event payload (visible in the order's timeline), not the banner copy, when
deciding what actually triggered the hold.

## Env kill switches

Every rule ships with its own switch so a false-positive storm is stoppable
by env change and restart, not by revert and redeploy. Requires an API
restart to take effect (`Settings` is read at process start).

| Variable                      | Default                                  | Disables                                      |
| ----------------------------- | ---------------------------------------- | --------------------------------------------- |
| `MANUAL_REVIEW_THRESHOLD_USD` | `40` (currently `12` in prod, see below) | `0`                                           |
| `RISK_SUM_24H_USD`            | `25`                                     | `RISK_SUM_24H_USD=0`                          |
| `RISK_SUM_7D_USD`             | `60`                                     | `RISK_SUM_7D_USD=0`                           |
| `RISK_VELOCITY_24H`           | `5`                                      | `RISK_VELOCITY_24H=0`                         |
| `RISK_DISTINCT_BUYERS_7D`     | `3`                                      | `RISK_DISTINCT_BUYERS_7D=0`                   |
| `RISK_LIQUID_BRANDS`          | `roblox,telegram-stars,steam`            | `RISK_LIQUID_BRANDS=` (empty)                 |
| `RISK_HOME_TIMEZONES`         | `Asia/Tashkent,Asia/Samarkand`           | `RISK_HOME_TIMEZONES=` (empty)                |
| `RISK_JITTER`                 | `true`                                   | `RISK_JITTER=false` (flat threshold, no band) |

`MANUAL_REVIEW_THRESHOLD_USD` was dropped from its normal default of `40` to
`12` on production ahead of the identity-window rules shipping, as an
interim mitigation for the split-order attack these rules now catch
properly. Whether to raise it back toward `40` — now that
`RISK_SUM_24H_USD`/`RISK_SUM_7D_USD` cover the ground the lowered threshold
was guarding — is an operator call once a week or two of the window rules'
alert volume has been observed; see the antifraud design doc's rollout
section.

## If alerts get noisy

Widen the specific window that's firing rather than disabling the rule
outright:

- Rolling-sum or velocity noise from legitimate repeat buyers → raise
  `RISK_SUM_24H_USD`/`RISK_SUM_7D_USD` or `RISK_VELOCITY_24H`.
- Shared-identity noise from a shared connection (office Wi-Fi, mobile
  carrier CGNAT, a family buying from one device) → raise
  `RISK_DISTINCT_BUYERS_7D`.
- Geo-mismatch noise from a legitimate market outside the current allowlist
  (e.g. RU marketing launching) → add the timezone to
  `RISK_HOME_TIMEZONES`, or drop the brand from `RISK_LIQUID_BRANDS` if the
  false-positive rate on that specific brand is the problem.

## Related

- [ADR-0047](../decisions/0047-manual-review-of-large-orders.md) — why hold,
  not block; the original amount-only gate
- [ADR-0062](../decisions/0062-antifraud-identity-windows.md) — the four
  identity-window rules added on top
- `docs/superpowers/specs/2026-08-30-antifraud-velocity-design.md` — full
  design, production numbers behind each default, rollout plan
- [paid-after-expiry.md](./paid-after-expiry.md) — dedicated procedure for
  `REASON_PAID_AFTER_EXPIRY`
- [wallet-refunds.md](./wallet-refunds.md) — refund procedure, including
  wallet-funded orders
