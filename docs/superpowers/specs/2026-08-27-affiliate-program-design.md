# Affiliate program

**Date:** 2026-08-27
**Status:** Accepted, not implemented
**Scope:** New `affiliate` API module + `apps/partners` (Next.js, `partners.yupay.uz`) + promo field on web & Mini App checkout + admin screens + scheduler job
**Touches:** `orders` (discount on the order path), `wallet` (five new account kinds), `stats`/`orders.revenue` (margin net of discount), `auth` (password hashing reused)

## Problem

YuPay has no way for a third party to bring customers and be paid for it. The
existing `promo` module is not that mechanism and cannot be stretched into it:
it credits a **fixed gift amount to the buyer's wallet after payment**
(`D user_wallet / C house_promo_expense`, `kind="promo.redeem"`), whereas an
affiliate code must **reduce the amount the customer pays, before payment**, and
must permanently bind that customer to the partner who introduced them.

Different moment in the order's life, different postings, different ownership.
Merged into one module they would produce a `kind` discriminator branching
through every method of working money code.

## Measured facts that shaped the design

Taken from production on 2026-08-27, not assumed:

- **Margin across 171 active SKUs: min 14.0%, average 17.1%, max 22.9%** of the
  sale price. Note that `Sku.margin_percent` stores a **markup on cost**
  (`price = cost * (1 + margin/100)`, `integrations/service._sell_price`), so
  the configured figures — min 16.3%, average 20.7%, max 29.7%, with 57 SKUs at
  exactly 20.0% — are markups and read higher than the margin they produce.
  Anyone reasoning about affiliate economics must use the margin-on-price
  numbers. A 20% discount would exceed the entire margin on **every SKU in the
  catalogue**. Break-even on the thinnest SKU, including 2% commission, is a
  discount of about 12.2%, which is why the ceiling is 10% and not the 20%
  originally sketched.
- **49.3% of delivered catalog orders are guest orders** (133 of 270) — no
  account, only an email. Attribution has nothing durable to attach to for half
  the traffic.
- **37.2% of buyers return; 1.97 orders per buyer.** Lifetime commission is
  real but roughly doubles the first order rather than dwarfing it. "Discount
  now, earn it back on repeats" is a 2× story, not a 10× one.
- **All 270 delivered orders are denominated in UZS**, and ledger accounts are
  already keyed by currency, so a partner balance in UZS needs no conversion
  layer.

## Decisions (from brainstorming)

Each was an explicit choice by the product owner:

- **Discount range 3–10%**, set per code by an admin, taken out of our margin.
  Not 3–20%: see the margin measurement above.
- **Commission 1–2%**, set per code by an admin, **of the order total after
  discount** — the number the customer actually paid.
- **Commission is paid on every order of an attributed buyer, including the
  first** (the one that also carried the discount).
- **Module inside the monolith, separate frontend.** Commission is derived from
  orders and the ledger lives here; a separate service would turn every accrual
  into a cross-service event whose loss is a partner's lost money.
- **A partner is a separate entity with its own login**, not a role on a `users`
  row.
- **Commission accrues after the order is delivered**, and becomes withdrawable
  only after a hold period. See "Parameters" for the value.
- **Partner promo codes require an account.** Guests cannot use them.
- **Attribution is permanent** — no expiry, no decaying rate.
- **Payouts are manual**: partner requests, admin approves, admin transfers by
  hand, admin marks it paid. No payout-provider integration in v1.
- **Abuse handling in v1**: block a partner from using their own code from a
  linked account; everything else is caught by the human approving the payout.
- **Onboarding**: admin approves → partner receives an email with a one-time
  set-password link.
- **v1 ships everything** — landing, application, approval, panel, code,
  attribution, commission, statistics, balance, withdrawal request — with the
  simplest possible withdrawal.
- **Subdomain: `partners.yupay.uz`.**

## Domain model

Six new tables.

**`affiliate_partners`** — the partner. An application and a partner are one
row, not two: the landing form inserts a row in status `pending`, the admin
moves it to `active`. Nothing is copied on approval and there is no state where
an application is approved but the account does not yet exist.

Columns: contact details, promotion channel, status
(`pending` / `active` / `suspended` / `rejected`), password hash (empty until
activation), optional link to a `users` row (for the own-code check),
timestamps.

**`affiliate_codes`** — code, owner, discount percent, commission percent,
active flag. The percentages live on the **code**, not the partner, so one
partner can run several codes on different channels with different terms at no
extra cost.

**`affiliate_attributions`** — `UNIQUE(user_id)`. A buyer belongs to exactly one
partner, forever, and the database guarantees it rather than the code. Also
records the code and the order that created the binding.

**`affiliate_commissions`** — `UNIQUE(order_id)`. One row per order; this
constraint is the whole of the accrual's idempotency. Records partner, code,
base amount, percent, amount, currency, status
(`pending` / `available` / `paid` / `void`) and `available_at`.

**`affiliate_payouts`** — partner, amount, card details, status
(`requested` / `approved` / `rejected` / `paid`), requester and processor
timestamps, admin note.

**`affiliate_sessions`** — partner refresh sessions, mirroring the rotation
policy of `auth`.

### Columns added to existing tables

- `orders.affiliate_code_id` (nullable FK) and `orders.discount_charged` — for
  the receipt and the order history.
- `order_items.discount_usd` — the per-line share of the discount. See
  "Margin analytics" below; this column is why the reporting stays correct.

## Money: the ledger

Five new account kinds. The postings copy the shape `promo.redeem` already
uses, so no new rules enter double-entry bookkeeping.

| Event                     | Posting                                          |
| ------------------------- | ------------------------------------------------ |
| Commission accrued        | `D partner_pending / C house_affiliate_expense`  |
| Hold period expired       | `D partner_balance / C partner_pending`          |
| Partner requests a payout | `D partner_payout_hold / C partner_balance`      |
| Admin transfers the money | `D house_affiliate_paid / C partner_payout_hold` |
| Admin rejects the request | `D partner_balance / C partner_payout_hold`      |

Account kinds and normal sides: `partner_pending` (D), `partner_balance` (D),
`partner_payout_hold` (D), `house_affiliate_expense` (D),
`house_affiliate_paid` (D). Partner accounts use `owner_type="partner"`.

Two properties follow from splitting the partner's money across three accounts:

1. **"Available to withdraw" is the balance of `partner_balance`**, not a
   computation over the commissions table. One source of truth.
2. **A payout request reserves the money immediately**, so two requests in a row
   cannot overdraw. The ledger invariant enforces this, not a check in the
   service.

### The discount is not a ledger entry

There is no posting for the discount and there must not be one. The customer
simply pays less — we receive 90 000 instead of 100 000; we do not pay anyone
10 000. Cost of goods is unchanged, so our margin is genuinely lower. That is a
fact about revenue, not an expense.

## The discount on the order path

### Preview is a separate call

The buyer must see the discount **before** paying, so there is an endpoint that
takes the cart and returns "valid, N%, was X, now Y". It creates nothing and
changes nothing.

**It never sets a price.** The client does not send an amount today either —
the server computes it from the SKU and the FX rate. The discount goes in the
same place: `OrderCreate` gains an optional code field, and the server
re-validates the code and recomputes the total itself. The preview response is
for display only. If the code is deactivated between preview and checkout, the
order is created without the discount rather than at the price the client
remembered.

### Six admission conditions, all server-side, all at order creation

1. The order is a **catalog** order, not a wallet top-up. Top-ups are 1:1;
   discounting one prints money.
2. The buyer is authenticated. Guests cannot use partner codes.
3. The buyer has no existing attribution.
4. The buyer has **no prior paid order**. Deliberately not "no prior order": an
   abandoned unpaid cart must not disqualify someone forever.
5. The code is active and its partner is active.
6. The partner is not redeeming their own code from a linked account.

Condition 4 is additionally guarded by rejecting a code when the buyer already
has an unpaid order carrying one — see "Known gap" below.

### Rounding

The discount is applied to the payable total and rounded to the currency's
quantum (1 UZS) — the buyer must see a whole number and neither Payme nor Click
accepts fractions. Separately, the same percentage is distributed across the
order lines in USD for analytics, proportionally, with the rounding remainder
assigned to the largest line.

These are two quantities in two currencies derived from one percentage. They
are not required to reconcile to the cent and should not be forced to: the
payable amount is authoritative.

### Attribution is created at payment, not at order creation

Otherwise an abandoned cart would permanently bind a buyer to a partner who
sold them nothing. The attribution row is written in the same transaction that
marks the order paid; `UNIQUE(user_id)` makes the race safe without locking.

**Known gap, accepted for v1:** a buyer can open two orders with two different
codes and pay both — two discounts, one attribution. Condition 4's extra guard
(reject a code while an unpaid coded order exists) narrows this to a
seconds-wide race costing one extra discount. Closing it fully would require a
per-user lock in order creation, which is not worth that price.

## Margin analytics

**This is the part that would have silently broken.**

Revenue and margin are not computed from `total_charged`. They are computed
from order lines — `unit_price_usd × rate_multiplier` — in
`orders/revenue.py`, with the invariant `gross − margin == cost`. The admin
dashboards, the per-brand breakdown and the per-product breakdown all read from
there (`stats/service.py`, `stats/analytics/business.py`).

A discount that only reduced `total_charged` would therefore be **invisible to
every report**. The admin would see full margin on precisely the orders that
have the least of it, and the discrepancy would surface weeks later as numbers
that do not add up.

The fix is `order_items.discount_usd`: `charged_usd_expr()` subtracts it once,
and every consumer — totals, brands, products — becomes correct without editing
each report. The invariant becomes `gross − discount − margin == cost` and that
extra term is explicit rather than assumed.

Most orders are single-line, so the distribution is usually trivial.

## Commission accrual

A new scheduler job, following the shape of the existing jobs in
`apps/scheduler/src/yupay_scheduler/jobs/`, running every 5 minutes with two
steps:

**Accrue.** Find delivered orders whose buyer has an attribution and which have
no commission row, and post `D partner_pending / C house_affiliate_expense`.
`UNIQUE(order_id)` makes double accrual impossible even if two ticks overlap. An
order missed for any reason is picked up by the next pass: the construction is
self-healing rather than one that needs manual reconciliation.

**Mature.** Find commissions whose hold period has expired and post
`D partner_balance / C partner_pending`.

Neither step touches the order fulfilment path. That path is already the
slowest in the system, and adding work to it to gain a minute of freshness is a
bad trade when a hold period follows anyway.

**Refunds.** A commission voided before maturity is reversed
(`C partner_pending / D house_affiliate_expense`). After maturity the admin
handles it by hand at payout time. Automatic clawback of already-available
money is not built in v1: digital goods are rarely refunded, and code that
moves money for a rare case is a bad trade.

## Parameters

Every number here is a setting with the default given, not a constant compiled
into the logic.

| Parameter                     | Default                                                   | Reasoning                                                                                                                                                                                                                                                                                   |
| ----------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discount percent per code     | admin-set, 3–10%                                          | Bounded by the measured 14.0% worst-case margin-on-price. Break-even including 2% commission is a ~12.2% discount, so a 10% ceiling keeps roughly 2 points of headroom on the thinnest SKU and about 6 on the typical one.                                                                  |
| Commission percent per code   | admin-set, 1–2%                                           | As specified by the product owner.                                                                                                                                                                                                                                                          |
| Hold period before withdrawal | 14 days from delivery                                     | Covers the realistic dispute window for digital goods and the acquirers' chargeback windows, without making a partner wait a month for their first payout.                                                                                                                                  |
| Accrual sweep interval        | 5 minutes                                                 | Freshness costs nothing here — the hold period dominates. Frequent enough that the panel never looks broken.                                                                                                                                                                                |
| Minimum payout amount         | 50 000 UZS                                                | Each payout is a manual bank transfer, so there must be a floor. At a ~12 000 UZS average order and 2%, this is roughly 200 attributed orders. **Revisit once real partner volumes exist** — set too high it blocks every small partner, and this number is an estimate, not a measurement. |
| Code format                   | 4–32 chars, `A-Z0-9-`, case-insensitive, stored uppercase | Partners advertise these aloud and in captions, so they must be short and unambiguous. Uniqueness is enforced by the database.                                                                                                                                                              |

**Commission currency is the order's currency** (UZS for all production orders
today). Ledger accounts are already keyed by currency, so a partner
accumulating in more than one would simply hold more than one account; no
conversion happens anywhere.

## API

**Buyer-facing** — one endpoint: validate a code against a cart, returning the
percent and the totals before and after.

This is a code-guessing surface, so the two-axis `ip_guard` applies. The
response must not reveal whether a code exists — only whether it is applicable
for this buyer — otherwise the endpoint becomes a directory of other people's
promo codes.

**Partner-facing** (`/v1/partners/…`): application submission (public, rate
limited), login, set-password, token refresh, profile with codes, statistics by
day/week/month/year, balance, paginated commissions, payout request and
history.

**Admin** (`/v1/admin/affiliate/…`): applications (list, approve, reject);
partners (list, codes, percentages, suspend); payouts (approve, reject, mark
paid).

## Partner authentication

The project must not gain a second hand-written authentication system — that is
exactly where security holes live. Partner sessions live in the affiliate
module's own table with the same rotation policy as `auth`, but password
hashing comes from the existing `auth.security` (argon2id with the capacity
limiter already tuned for this box). The module boundary stays clean and the
cryptography stays in one place.

## Frontend

### Promo field on checkout

Both checkout files are already far over the size limit —
`apps/web/src/components/store/PurchasePanel.tsx` is 2037 lines and
`apps/miniapp/src/pages/TopUp.tsx` is 2172, against a 300-line soft limit.
Adding an inline block to either would make that worse.

So each surface gets a **self-contained component** owning the input, the
validation request, its state and the before/after display. The host file gains
about ten lines: render it, subtract the resulting discount from the displayed
total. On web the price currently renders on the pay button
(`{t("pay")} · {selectedPriceLabel}`); the Mini App does the same with
`finalPrice`. Both read one value, and that is the value that changes.

The components are per-surface, not shared. The logic inside is roughly thirty
lines of a TanStack Query call; the presentation and the message catalogues
differ (`web.json` vs `miniapp.json`, storefront vs Telegram design language),
and the two surfaces do not share checkout components today. What is shared —
the response type — arrives free from the generated client.

**Placement:** between the payment-method block and the pay button, on both
surfaces.

**Applied state:** code name and percent, the old total struck through, the new
total beside it, and the amount saved.

**Error states**, each with its own message in all three locales: unknown or
disabled code; already used; first order only; own code. Plus a distinct branch
for guests on web — guests cannot use partner codes, so the field must invite
them to sign in rather than fail silently.

A visible promo field on checkout is generally known to increase abandonment —
people leave to hunt for a code. Here the traffic arrives holding one, so
visible is the right default; this is noted so the trade-off is a choice rather
than an oversight.

### `apps/partners` on `partners.yupay.uz`

**Landing** — static, SEO, three locales: how it works, what can be earned, an
earnings calculator, FAQ, application form.

**Panel** behind authentication: overview with the balance split into available
and held, an earnings chart, activation counters by day/week/month/year; codes
with ready-made links and copyable material; the list of referred buyers;
withdrawals with history.

Design tokens come from `packages/ui` so it reads as YuPay, but the panel gets
its own dense, dark, dashboard-like treatment.

Memory is not a constraint: production shows 18 GB available of 23 GB, with
5.3 GB in use across 20 containers.

### Admin

Three new screens in the existing SPA: applications, partners, payouts.
Applications and payouts carry a pending count in the navigation — otherwise
they will be forgotten.

## Testing

The module moves money, so the coverage gate is 95%, not 80%. Integration tests
must cover:

- rejection under each of the six admission conditions;
- accrual idempotency with two overlapping ticks;
- maturation on schedule;
- two payout requests unable to overdraw the balance;
- commission reversal on refund before maturity;
- the discount appearing correctly in the margin reports (the regression this
  design exists to prevent).

## Definition of done additions

- One migration: six tables, the new order/order-item columns, the new account
  kinds.
- Three ADRs: a new frontend application; separate partner authentication;
  commission by scheduled sweep rather than inline accrual.
- All three locales for every new string.
- `make gen-api` plus a regenerated TS client.
- `docs/architecture/module-map.md`, a module `README.md`, a sequence diagram
  for the attribution + commission flow, and a runbook for the payout process.

## Build order

Seven independently shippable steps:

1. Migration, module, ledger accounts, accrual sweep — with tests, no UI.
2. The discount on the order path, including the margin analytics fix.
3. The promo field on web and Mini App.
4. Partner authentication and the panel API.
5. `apps/partners` — landing and panel.
6. Admin screens.
7. Infrastructure: DNS, certificate, Caddy, CI build, deploy.

Steps 1 and 2 can go to production invisibly — no codes have been issued yet.
That is deliberate: the money machinery gets to live on production before
partner traffic arrives.

## Out of scope for v1

- Automated payouts through a payment provider.
- Automatic clawback of matured commission after a late refund.
- Automated fraud scoring (shared IP, shared device, registration bursts).
- Multi-level / sub-affiliate structures.
- Guest attribution.
- Attribution expiry or decaying commission rates.
