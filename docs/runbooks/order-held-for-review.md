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

Two related mechanisms, both ADR-0063, are covered further down: a
**deadline** on how long a hold from any rule below may sit before it is
refunded automatically, and the **pre-charge veto** — the one control in
this document that actually refuses a charge instead of just holding the
goods after it.

## The alert

A held order pages the admin Telegram channel (`kind="order_held_for_review"`),
one message per hold, e.g.:

> 🔍 Крупный заказ — на проверке
> Заказ: `a1b2c3d4…`
> Сумма: **550 000 UZS** ($40.12)
> _Оплачен, выдача НЕ запущена. Проверь плательщика, затем выдай или верни деньги._

The alert deliberately carries **no IP, device, email, or other identity** —
`hold_for_review`'s payload and the alert text only ever contain the reason
(and counts, when a caller passes them — no current call site does yet; see
ADR-0044/§9 on why raw identity data doesn't get copied around). Finding the
rest of a linked group is a step you do in the admin panel, described below.

## The six reasons

| Reason (`order_events.payload.reason`)                        | Fires when                                                                                                                                                                                                                                                                                                                                                                                                                          | Detail                                                                                                                                                                  |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `amount_at_or_above_threshold` (`REASON_LARGE_AMOUNT`)        | This order's `total_usd` is at or above the effective threshold. Threshold is jittered per order id within `[0.6, 1.0) × MANUAL_REVIEW_THRESHOLD_USD` so probing for the edge finds a band, not a line — the same order always gets the same effective threshold, but two different orders at the same nominal amount can land on either side of it.                                                                                | ADR-0047                                                                                                                                                                |
| `paid_after_order_expired` (`REASON_PAID_AFTER_EXPIRY`)       | The acquirer settled the payment after the order had already been marked `expired`. The sale is real, but it was priced and stocked ten minutes ago.                                                                                                                                                                                                                                                                                | [paid-after-expiry.md](./paid-after-expiry.md) has the full procedure — different for wallet top-ups vs. catalog orders, and for timeout vs. operator-cancelled orders. |
| `identity_rolling_sum_exceeded` (`REASON_ROLLING_SUM`)        | Orders sharing an identity (buyer, IP, device, or delivery target) sum to `RISK_SUM_24H_USD` or more within 24h, or `RISK_SUM_7D_USD` or more within 7 days — many small orders instead of one large one. **The sum includes this order itself: a single order at or above the cap holds on its own, with zero linked orders.** Check the window before assuming a series exists.                                                   | ADR-0062                                                                                                                                                                |
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

## Deadline: a hold is not indefinite (ADR-0063)

A held order used to wait on an operator with no deadline. It no longer
does: `orders.risk.auto_refund_expired_holds`, run by `apps/scheduler`'s
`held_order_refund` job every 15 minutes, refunds a still-`paid` order once
it has been sitting on `order.held_for_review` for
`RISK_HOLD_AUTO_REFUND_HOURS` (default **24**) with nobody releasing or
refunding it by hand.

- **Every hold reason is in scope**, including `REASON_PAID_AFTER_EXPIRY` —
  if no human decided within the window, returning the money is the safe
  default for both fraud and simple confusion.
- **Released orders are never touched.** Release
  (`fulfillment.start_for_order`) is the only thing that ever moves a paid
  order off `status="paid"` for a reason other than a refund, so an order
  the sweep would otherwise pick up is already out of scope the moment an
  operator releases it — even though the old `order.held_for_review` event
  is still on its timeline.
- **The refund is the same one you'd trigger by hand**:
  `payments.service.refund_admin`, full amount, actor stamped
  `admin:auto-refund-sweep` (grep-able as the sweep's own signature, not a
  real operator), reason `auto_refund_hold_expired`. It posts the same
  ledger reversal, walks the order to `refunded`, and cancels any open
  fulfilment task — nothing about the refund itself is special-cased.
- **Idempotent across ticks**: the refund is keyed by a deterministic
  `auto-refund:<order_id>` idempotency key, so a tick that crashes mid-sweep
  and reruns can't double-refund. In practice the order's own `status`
  already leaves `paid` the moment the first attempt commits, so a re-run
  never even re-selects it.
- **One admin alert per refunded order** — 💸 title, the amount, which
  deadline expired, and that this is the configured policy, not an
  incident. Distinct from the original hold alert; expect both on an order
  nobody acted on in time.
- **Turning it off**: `RISK_HOLD_AUTO_REFUND_HOURS=0` returns to today's
  indefinite hold (a fire-drill lever, not a normal operating mode — a
  disabled sweep means held orders are 100% on operator attention again).

## The pre-charge veto (ADR-0063)

Everything above is a **post-payment** control — the money is already taken
by the time any rule runs. The pre-charge veto is the one exception: it
runs _before_ the charge, refusing payment outright for a guest or a fresh
account (zero delivered orders) whose evidence puts them outside
`RISK_HOME_COUNTRIES`/`RISK_HOME_TIMEZONES`. A signed-in buyer with at least
one delivered order is exempt unconditionally — the same trusted-buyer bar
the geo-mismatch hold rule already uses.

Two enforcement points, one shared decision core (`_veto_decision`), so
they can never disagree:

| Where                                                                        | What the buyer sees                                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Point A** — Payme `CheckPerformTransaction`, Click `Prepare`, Uzum `Check` | The acquirer's own generic decline screen. This is the backstop for orders created before the rule, races, and a context that changed after creation — a guest already caught by point B never reaches this stage.                                                                      |
| **Point B** — order creation (`POST /api/v1/orders`)                         | HTTP 422, `payment-unavailable-abroad`. The storefront and Mini App show `store.errAbroad` / `topup.errAbroad` near the pay button — copy leads with order history, not "sign in," since a signed-in buyer with zero deliveries hits this while already signed in. No order is created. |

**Both branches (`VETO_FOREIGN_COUNTRY`, `VETO_FOREIGN_TIMEZONE`) refuse
identically from the outside** — the acquirer's own error at point A, the
one fixed message at point B. Only `order_events.payload.reason` (on the
`order.precharge_vetoed` event point A writes) says which signal actually
fired; nothing exposed to the buyer or the acquirer distinguishes them.

**The Cloudflare toggle.** The primary signal, `order_evidence.ip_country`,
is Cloudflare's edge-resolved country (`CF-IPCountry`), populated only once
the (free) **IP Geolocation** toggle is turned on in the Cloudflare
dashboard for the zone. Until it is:

- `ip_country` is `NULL` on every order, and the veto runs on the
  **browser-reported timezone fallback only** — the same signal the
  post-payment hold rule already uses, so there is no day-one cliff.
- After flipping the toggle, place one test order and confirm its evidence
  row's `ip_country` is populated (`GET /admin/orders/{id}/evidence`) before
  trusting the country signal in the `order.precharge_vetoed` counts.
- The edge Caddy strips any inbound `Cf-Ipcountry` header on traffic that
  didn't arrive via Cloudflare, so a spoofed header from outside Cloudflare
  can't forge a country. If the country signal in `precharge_vetoed` events
  ever goes quiet after the toggle was confirmed on, suspect an origin
  bypass ahead of Caddy, not the veto itself.

**Turning it off**: `RISK_PRECHARGE_VETO=false` disables the refusal
entirely; the post-payment hold rules above are unaffected and keep
running — this only removes the pre-charge step.

## Env kill switches

Every rule ships with its own switch so a false-positive storm is stoppable
by env change and restart, not by revert and redeploy. Requires an API
restart to take effect (`Settings` is read at process start).

| Variable                      | Default                                  | Disables                                                                                                                 |
| ----------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `MANUAL_REVIEW_THRESHOLD_USD` | `40` (currently `12` in prod, see below) | `0`                                                                                                                      |
| `RISK_SUM_24H_USD`            | `25`                                     | `RISK_SUM_24H_USD=0`                                                                                                     |
| `RISK_SUM_7D_USD`             | `60`                                     | `RISK_SUM_7D_USD=0`                                                                                                      |
| `RISK_VELOCITY_24H`           | `5`                                      | `RISK_VELOCITY_24H=0`                                                                                                    |
| `RISK_DISTINCT_BUYERS_7D`     | `3`                                      | `RISK_DISTINCT_BUYERS_7D=0`                                                                                              |
| `RISK_LIQUID_BRANDS`          | `roblox,telegram-stars,steam`            | `RISK_LIQUID_BRANDS=` (empty)                                                                                            |
| `RISK_HOME_TIMEZONES`         | `Asia/Tashkent,Asia/Samarkand`           | `RISK_HOME_TIMEZONES=` (empty)                                                                                           |
| `RISK_JITTER`                 | `true`                                   | `RISK_JITTER=false` (flat threshold, no band)                                                                            |
| `RISK_DEVICE_IDENTITY`        | `false`                                  | already off by default; opt in with `RISK_DEVICE_IDENTITY=true`                                                          |
| `RISK_PRECHARGE_VETO`         | `true`                                   | `RISK_PRECHARGE_VETO=false`                                                                                              |
| `RISK_HOME_COUNTRIES`         | `UZ`                                     | `RISK_HOME_COUNTRIES=` (empty disables the country check only — the timezone fallback still needs `RISK_HOME_TIMEZONES`) |
| `RISK_HOLD_AUTO_REFUND_HOURS` | `24`                                     | `RISK_HOLD_AUTO_REFUND_HOURS=0` (back to an indefinite hold)                                                             |

`RISK_DEVICE_IDENTITY` ships **off**, not on with the other three window
keys (buyer, IP, delivery target). Measured on production: this audience's
`device_hash` (a digest of user-agent + timezone + locale + screen, see
ADR-0044) is not unique enough on its own — two device hashes already span
4 distinct buyers each and two more span 3, which is exactly
`RISK_DISTINCT_BUYERS_7D`'s default. That is a homogeneous mobile fleet
(identical phone models, identical carrier locale) colliding, not a resale
ring. Turning device on there without checking would hold real, unrelated
customers.

Run this before enabling it, on your own traffic — it counts only, no raw
identity comes back:

```sql
SELECT
  encode(digest(
    coalesce(e.user_agent, '') || '|' ||
    coalesce(e.client_hints->>'timezone', '') || '|' ||
    coalesce(e.client_hints->>'locale', '') || '|' ||
    coalesce(e.client_hints->>'screen', ''), 'sha256'), 'hex') AS device_hash,
  count(DISTINCT coalesce(o.user_id, o.guest_email)) AS distinct_buyers
FROM order_evidence e
JOIN orders o ON o.id = e.order_id
WHERE o.paid_at >= now() - interval '7 days'
  AND o.purpose = 'catalog'
GROUP BY 1
HAVING count(DISTINCT coalesce(o.user_id, o.guest_email)) >= 3
ORDER BY distinct_buyers DESC;
```

(Same digest formula as the 0059 backfill, recomputed rather than trusted
from the stored `device_hash` column, so it's correct even against rows
written before that migration ran.) Rows back means the same collision this
audience already showed — leave it off. A clean result on your own traffic
is what "enable after measuring" means.

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
- [ADR-0063](../decisions/0063-precharge-veto-and-auto-refund.md) — the
  pre-charge veto and the auto-refund deadline, both above
- `docs/superpowers/specs/2026-08-30-antifraud-velocity-design.md` — full
  design, production numbers behind each default, rollout plan
- `docs/superpowers/specs/2026-08-30-precharge-geo-veto-design.md` — full
  design for the veto and the sweep, including the rollout plan
- [paid-after-expiry.md](./paid-after-expiry.md) — dedicated procedure for
  `REASON_PAID_AFTER_EXPIRY`
- [wallet-refunds.md](./wallet-refunds.md) — refund procedure, including
  wallet-funded orders
