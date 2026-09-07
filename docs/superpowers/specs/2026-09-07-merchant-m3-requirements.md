# Merchant B2B — M3 requirements added after M2 (owner decisions, 2026-09-07)

M2 shipped `/merchant/v1` (auth, `/me`, `/catalog`, order placement, order and
transaction reads, contract docs). Three things surfaced during M2's reviews
that the owner has now ruled on. Two of them land in M3, alongside the webhook
outbox and SSRF hardening the roadmap already lists.

Recorded here rather than in a progress ledger because M3 will be planned in a
different session, and the third item below is the one that actually needs
design work.

---

## 1. Settled in M2, not M3 — the drift rule is quote-only

`POST /merchant/v1/orders` now charges **our** current price whenever the
merchant's `expected_price` is within ±2%, instead of the lower of the two.
Beyond the band it still refuses with `price_changed` carrying our price.

Superseded spec §8.4. Reasoning lives in `pricing.price_to_charge` and
ADR-0069's amendment. Listed here only so M3 does not re-derive it.

## 2. A stalled order must say it is stalled _(owner)_

**Today.** When a supplier refuses because _our_ balance with them is too low,
the fulfilment task fails into the admin inbox with an alert, but the order
item deliberately stays `in_progress` — retail's rule, so a storefront buyer
sees "обработка" rather than an error for something an admin will fix in
minutes. A merchant reading `GET /merchant/v1/orders/{id}` therefore sees
`status: "fulfilling", failure_reason: null` — **identical to an order placed
thirty seconds ago**, indefinitely.

**Why that is worse for a reseller than for a buyer.** A retail buyer has a
support chat and a refund button. A reseller has an SLA to their own customer
and a polling loop with no terminal condition: nothing in the response ever
distinguishes "progressing" from "stuck, a human is needed".

**Required.** The order keeps hanging in fulfilment — that part is right, the
money is correctly debited and the work will complete. Add a third,
**non-terminal** `failure_reason` value meaning _in progress, delayed on our
side — do not re-order, do not refund your customer yet_. Status stays
`fulfilling`.

Additive, so it fits inside `/merchant/v1`: the contract already documents
that `failure_reason` may be non-null while `fulfilling`. The README's
"treat a long `fulfilling` as in progress" guidance is replaced by something a
machine can act on.

## 3. Auto-refund when the supplier refuses and returns the money _(owner)_

**Required.** When an order has already been handed to a supplier for
fulfilment and the supplier **refuses and returns the funds to our balance**,
we refuse the order too and **automatically refund the merchant's deposit**.

This is the first merchant refund path of any kind. M2 has none, which is why
`refunded_usd` is currently `"0.00"` on every order.

### What M3 must decide — do not treat this as fully specified

- **The signal.** "The supplier returned the money" has to be something we
  actually observe. Decide per adapter which refusal responses carry that
  guarantee, which mean "refused but the money is spent", and which are
  unknown. An auto-refund triggered on an unknown outcome refunds money we did
  not get back; one that never triggers leaves the merchant short. Neither
  failure is acceptable silently, so the unknown case needs a named state and
  a human, not a guess.
- **Attribution — this is a real defect M2 leaves behind.** `refunded_usd`
  filters ledger transactions on `reference_type == "order"`, but
  `credit_deposit` — the only surface that credits a deposit today — posts
  `Reference(type="merchant", id=merchant_id)`. So a support-issued manual
  credit is **invisible on the order by construction**, not merely until a
  refund path exists. The auto-refund must post against the **order**, and the
  manual stopgap in `docs/runbooks/merchant-b2b.md` should be revisited at the
  same time.
- **Idempotency.** The refund must be keyed so a retried or re-driven
  fulfilment cannot refund twice — the same discipline as
  `merchant-order:{order_id}` on the charge leg.
- **The legs.** Exact mirror of the charge, per the module README's posting
  table. Do not re-derive directions.
- **What the merchant reads.** Which `status` and `failure_reason` the order
  ends in, and how the refund appears in `GET /merchant/v1/transactions`.
- **Retail parity.** Check whether the same supplier-refunded-us case exists on
  the retail path and what it does today, so the two do not diverge silently.

## 3b. Record what the merchant quoted _(follow-up to item 1)_

Nothing stores a merchant's `expected_price` on a successful order — it reaches
only the _rejection_ body and the request digest. So after the drift rule
changed we cannot measure, retrospectively, how often a merchant quoted low, or
what the old rule had been costing.

It matters less now that we charge our own price either way, but it still
leaves two gaps: the runbook's regression query has to _recompute_ list price
from cost and markup, which will produce false positives once
`markup_adjustment_pp` is used for real; and a pilot integrator arguing about a
charge has no record of what they sent. A quoted-price column on
`order_items` (or the order) closes both cheaply.

## 4. Carried into M3 from M2's reviews (not owner decisions, but due)

- `client_ip` trusts the first `X-Forwarded-For` entry with no peer check. That
  assumption used to risk a mis-attributed rate-limit counter; since M2 it also
  decides whether a merchant's IP allowlist can be bypassed with one header.
  Its safety currently rests entirely on the edge overwriting the header
  (`infra/edge/Caddyfile` does, via `header_up`, and the Cloudflare branch is
  gated on a `remote_ip` matcher).
- Two error-body idioms render differently from the same `AppError` class: 98
  raise sites pass `extra={...}` (nested under `extra`), while the merchants
  module passes flat kwargs (top-level). An API whose error shape depends on
  which idiom a raise site used cannot be documented truthfully — during M2 two
  careful readers derived opposite answers from one file. Normalise.
- CI's `openapi-drift` check has a half that can never fail:
  `packages/api-client/src/generated/` is gitignored, so the
  `git status --porcelain` half of the check sees nothing. The schema half
  works.
