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
- **Fail, without a refund** — `POST /admin/orders/{id}/fail`
  (`orders.service.mark_order_failed_admin`) closes a held order as
  `failed`. **It moves no money.** For a held order specifically: **refund
  first, then fail — never fail a held order bare.** A bare fail moves the
  order off `status="paid"`, which is exactly what the auto-refund sweep
  below watches, so failing it first silently pulls the order out of that
  net: the payment stays `succeeded`, the customer's money stays taken, and
  nothing will ever prompt anyone to return it again. If you meant "this
  order is dead, close it out," that requires an explicit refund — `fail` is
  for closing an order the money question is already settled on (e.g. after
  a manual refund, or one that was never actually paid).
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
`held_order_refund` job every 15 minutes, refunds — or, for a cabinet-only
acquirer, escalates (see below) — a still-`paid` order once it has been
sitting on `order.held_for_review` for `RISK_HOLD_AUTO_REFUND_HOURS` with
nobody releasing or refunding it by hand.

**Ships disarmed (`RISK_HOLD_AUTO_REFUND_HOURS=0`).** Arming it straight to
a live value on day one would auto-refund whatever backlog of held orders
already existed before an operator ever looked at them. Triage that backlog
by hand first, then arm the sweep with `RISK_HOLD_AUTO_REFUND_HOURS=24` —
the value every environment runs it at once armed.

- **Every hold reason is in scope**, including `REASON_PAID_AFTER_EXPIRY` —
  if no human decided within the window, returning the money (or escalating
  it to a human to return, on a cabinet-only provider) is the safe default
  for both fraud and simple confusion.
- **Released orders are never touched — checked twice.** Release
  (`fulfillment.start_for_order`) is the only thing that ever moves a paid
  order off `status="paid"` for the ordinary "an operator acted" case, so a
  released order is already out of scope of the batch this sweep selects —
  even though the old `order.held_for_review` event is still on its
  timeline. The sweep also re-checks under a row lock immediately before
  each refund, not only when the batch was first selected: up to 50 orders
  are processed one at a time with real gateway calls in between, long
  enough for a release (or the fulfilment saga delivering) to land while an
  order is still waiting its turn — that re-check is what makes the
  difference between "was eligible a minute ago" and "is eligible right
  now," and it is the actual guarantee, not the batch selection alone.
- **Where the gateway supports a merchant-initiated refund** (`octo`,
  `wallet`), **the refund is the same one you'd trigger by hand**:
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
- **Payme, Click, and Uzum never reach `refund_admin` at all** — see
  "Cabinet-only acquirers: escalation instead of auto-refund" below.
- **Turning it off**: `RISK_HOLD_AUTO_REFUND_HOURS=0` returns to an
  indefinite hold (also the ships-off default — see above; a disabled sweep
  means held orders are 100% on operator attention again).
- **Known gaps — neither is a bug, both need an operator to close them by
  hand:**
  - A held order closed with a bare **fail** (`POST /admin/orders/{id}/fail`,
    no refund) drops out of this sweep's selection with its payment still
    `succeeded` — the money sits there until someone explicitly refunds it.
    See the caution under **Release vs. refund** above:
    **refund a held order before failing it, never fail it bare.**
  - A held order an admin **partially refunds** by hand stays `status="paid"`
    (a partial refund never walks the order FSM) with its payment
    `partially_refunded`. The sweep's selection excludes it explicitly so it
    is never re-attempted and never fails `refund_admin`'s "already
    refunded" guard every 15 minutes — but that also means the sweep will
    never finish the job for you. Finishing a partially refunded hold (a
    second partial, or accepting the remainder is retained) is a manual
    call.

### Cabinet-only acquirers: escalation instead of auto-refund

Payme, Click, and Uzum have **no merchant-initiated refund call** — their
`payments.gateways.{payme,click,uzum}.py` adapters unconditionally raise on
`refund()` (see `docs/architecture/module-map.md` and
[payme-troubleshooting.md](./payme-troubleshooting.md#the-refund-via-cabinet-flow)
for the shape of it). Sending one of these through `refund_admin` would not
be a retryable failure — it would fail identically on every one of the
sweep's 15-minute ticks forever, with nobody ever told. The sweep checks the
payment's provider **before** attempting a refund, so a held order paid
through one of these three is never handed to `refund_admin` at all:

1. It writes one `order.auto_refund_escalated` event (`provider`,
   `deadline_hours` — no PII) and sends **one** admin alert — «деньги надо
   вернуть из кабинета эквайера», the order id, amount + currency, and the
   provider.
2. The next tick's selection query excludes any order that already has an
   `order.auto_refund_escalated` event, so it is never re-alerted and never
   re-attempted.

**Operator steps for an escalated order:**

1. Open the transaction in the acquirer's own cabinet (Payme / Click /
   Uzum) and issue the refund there — the acquirer, not YuPay, is the only
   place that can actually move this money back.
2. The acquirer calls back on its own SLA (Payme's `CancelTransaction`, the
   Click/Uzum equivalents) and we auto-reconcile: the order flips to
   `refunded` on its own, through the same `_apply_refund_reversal` core an
   admin refund uses.
3. Confirm via `GET /api/v1/admin/payments/{payment_id}` that the payment
   actually reached `refunded`. If the acquirer's own cabinet refund is
   refused (e.g. Payme `-31007`, Uzum `10017` — a partially delivered
   order), that acquirer's own troubleshooting doc has the manual
   reconciliation steps.

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

| Variable                      | Default                                  | Disables                                                                                                                                           |
| ----------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MANUAL_REVIEW_THRESHOLD_USD` | `40` (currently `12` in prod, see below) | `0`                                                                                                                                                |
| `RISK_SUM_24H_USD`            | `25`                                     | `RISK_SUM_24H_USD=0`                                                                                                                               |
| `RISK_SUM_7D_USD`             | `60`                                     | `RISK_SUM_7D_USD=0`                                                                                                                                |
| `RISK_VELOCITY_24H`           | `5`                                      | `RISK_VELOCITY_24H=0`                                                                                                                              |
| `RISK_DISTINCT_BUYERS_7D`     | `3`                                      | `RISK_DISTINCT_BUYERS_7D=0`                                                                                                                        |
| `RISK_LIQUID_BRANDS`          | `roblox,telegram-stars,steam`            | `RISK_LIQUID_BRANDS=` (empty)                                                                                                                      |
| `RISK_HOME_TIMEZONES`         | `Asia/Tashkent,Asia/Samarkand`           | `RISK_HOME_TIMEZONES=` (empty)                                                                                                                     |
| `RISK_JITTER`                 | `true`                                   | `RISK_JITTER=false` (flat threshold, no band)                                                                                                      |
| `RISK_DEVICE_IDENTITY`        | `false`                                  | already off by default; opt in with `RISK_DEVICE_IDENTITY=true`                                                                                    |
| `RISK_PRECHARGE_VETO`         | `true`                                   | `RISK_PRECHARGE_VETO=false`                                                                                                                        |
| `RISK_HOME_COUNTRIES`         | `UZ`                                     | `RISK_HOME_COUNTRIES=` (empty disables the veto whenever a country is known — the timezone fallback applies only to orders with no country at all) |
| `RISK_HOLD_AUTO_REFUND_HOURS` | `0` (ships disarmed; arm with `24`)      | `RISK_HOLD_AUTO_REFUND_HOURS=0` (already the default — an indefinite hold)                                                                         |

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

## Click-agreed rules (2026-09-02)

Added after the August carding wave, in the shapes Click's fraud team asked
for; each is a hold (manual release), never a silent block, and each is off
until its env var is set:

| Rule                                                                                          | Env                                                                             | Agreed with Click | Live (2026-09-14)    |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------- | -------------------- |
| Lower threshold for liquid brands (Stars/Roblox/Steam)                                        | `RISK_LIQUID_REVIEW_THRESHOLD_USD`                                              | 10                | 40 (≈ 481 000 UZS)   |
| New-buyer caps: orders per 24h / USD per 24h, identity younger than `RISK_NEW_BUYER_AGE_DAYS` | `RISK_NEW_BUYER_VELOCITY_24H`, `RISK_NEW_BUYER_SUM_24H_USD`                     | 3 / 8             | 8 / 60               |
| Night multiplier on both thresholds, Tashkent hours                                           | `RISK_NIGHT_START_HOUR`/`RISK_NIGHT_END_HOUR`/`RISK_NIGHT_THRESHOLD_MULTIPLIER` | 22 / 7 / 0.5      | 22 / 7 / **1** (off) |
| Copy of every hold to the shared fraud group with Click (masked recipient, no identities)     | `TG_FRAUD_CHAT_ID`                                                              | the group's id    | the group's id       |

**The live column is looser than the agreed one, on purpose and with the
owner's decision.** Two columns rather than one because these numbers are a
commitment to an acquirer, not a tuning knob: anyone changing them needs to
see what was promised, and a single "prod value" column silently overwrote
that the first time it drifted (liquid went 10 → 24 with nothing recording
it). Loosening any row is a conversation with Click's fraud team, not an env
edit. What made the loosening defensible: card-not-present payment from
unauthorised cards was switched off across all providers, which removed the
attack these rules were shaped around — the last hold that caught a real
fraud was 2026-08-30.

Regular customers skip the new-buyer caps — but only because
`review_reason` asks the database for delivered history. The in-window check
inside `_new_buyer_reason` ("any linked order older than
`RISK_NEW_BUYER_AGE_DAYS`") cannot do it: `_gather`'s sibling window is
itself 7 days, so with the default age of 7 no sibling is ever old enough.
This section claimed the exemption worked from 2026-09-02, and it did not;
see the measurement below for what that cost.

## Measured on production, 2026-09-14

**44% of orders were being held.** 135 holds on 307 paid catalog orders in the
twelve days after the Click rules went in — the owner's report was "almost
every second or third order", and that is exactly right.

Method, so the next person can redo it rather than re-argue it: 706 paid
catalog orders over 37 days were exported with their identity columns (buyer,
evidence IP, delivery targets, brand slugs, delivered history) and replayed
through the real `risk.py` functions — `_amount_reason`, `_liquid_amount_reason`,
`_window_reason`, `_new_buyer_reason`, `_geo_reason` — composed in
`review_reason`'s order. The replay reproduces the amount rule to within one
order (78 predicted, 77 actual) and velocity exactly, at a base of 18, which is
what the env held for most of that window.

### What the holds caught

Four orders in 30 days, all before the unauthorised-card switch-off, all on
liquid brands, all $50 or more: `другая страна` ×2 ($300, $250), `нужна
верификация` ($120), `карта 3 го лица` ($50.11). A fifth non-delivered hold
($10.26) was **not** a catch — an operator released it and it then failed on
stock. Everything else the rules held was delivered.

### Why raising the threshold alone did nothing

The owner raised `MANUAL_REVIEW_THRESHOLD_USD` from 18 to 24 and saw no
change. Replayed: raising it all the way to 66 and switching the night
multiplier off moves the hold rate from 38% to 34%, because the identity rules
simply pick up what the amount rule releases. The dominant rule was the
new-buyer cap — 72 of 99 holds — via the seasoning defect above.

Two numbers that are not the numbers an operator types:

- **Jitter** (`RISK_JITTER`) spreads the effective threshold over
  `[0.6 × base, base)`, so a configured $66 starts holding at $39.60.
- **The night multiplier** halved that again between 22:00 and 07:00
  Tashkent. A configured $24 was holding $7.20 orders at night — a 3.3× gap
  between the typed number and the binding one. This is the single most
  useful fact for anyone tuning these.

### Live configuration after the change

| Env                                | Value | ≈ UZS at 12 030/$ | What it ceilings                         |
| ---------------------------------- | ----- | ----------------- | ---------------------------------------- |
| `MANUAL_REVIEW_THRESHOLD_USD`      | 66    | 793 980           | one order                                |
| `RISK_LIQUID_REVIEW_THRESHOLD_USD` | 40    | 481 200           | one order on Stars/Roblox/Steam          |
| `RISK_SUM_24H_USD`                 | 150   | 1 804 500         | one identity per day                     |
| `RISK_SUM_7D_USD`                  | 400   | 4 812 000         | one identity per week                    |
| `RISK_VELOCITY_24H`                | 12    | —                 | orders per identity per day              |
| `RISK_NEW_BUYER_VELOCITY_24H`      | 8     | —                 | same, first 7 days, no delivered history |
| `RISK_NEW_BUYER_SUM_24H_USD`       | 60    | 721 800           | same, in money                           |
| `RISK_DISTINCT_BUYERS_7D`          | 5     | —                 | buyers behind one IP or device           |
| `RISK_NIGHT_THRESHOLD_MULTIPLIER`  | 1     | —                 | night no longer tightens anything        |

Replayed over the same twelve days this holds **24 orders of 307 (7.8%)**,
against 135 before, and **10 night holds instead of 43** — under one a night,
which is what "orders should not sit until morning" came down to in practice.
The caps are deliberately set above measured customer behaviour (p95 of a real
identity's 24h spend was $144) rather than below it, because every one of the
57 identity-rule holds in that window was delivered.

`RISK_DISTINCT_BUYERS_7D` went 3 → 5 because 3 buyers behind one address is an
ordinary household or office — the largest real collision measured over 14 days
was exactly 3, and it produced four holds of $1–$15.

### What the ceilings do and do not protect

They bound **one identity**. Someone with several unrelated identities gets the
per-identity ceiling several times over; nothing here caps that, and it is not
meant to — the control that removed the carding wave was switching off payment
from unauthorised cards, which is upstream of every rule in this file. If that
setting is ever reversed, these numbers must come back down first.
