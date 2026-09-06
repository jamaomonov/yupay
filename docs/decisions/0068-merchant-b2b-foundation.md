# 0068 — Merchant B2B foundation: actor arm, deposit-as-ledger, one-home pricing

- Status: accepted
- Date: 2026-09-07
- Spec: `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
- Plan: `docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md`

## Context

M1 of the reseller platform lays the merchant entity into a live retail
system: schema, a USD deposit, wholesale pricing, and admin controls. Four
decisions made here are the kind a future maintainer will second-guess; this
record keeps them from being re-litigated. The spec carries the full product
rationale — this ADR records only the load-bearing engineering choices.

## Decisions

### 1. Merchants are a third actor arm on `orders`, FK `ON DELETE RESTRICT`

`orders` already enforced exactly-one-of `user_id` / `guest_email`; migration
0066 widens the CHECK to exactly-one-of-three with `merchant_id`. RESTRICT —
deliberately not `SET NULL` like `user_id` — because a merchant order is
financial history backed by a deposit debit: a merchant with orders gets
**frozen**, never deleted. A synthetic per-merchant `users` row was rejected:
it would leak merchant orders into every user-scoped query, stat and mailing.

The 0066 downgrade refuses (count + `RuntimeError`, advisory not race-proof)
rather than silently orphaning money rows.

### 2. The deposit is a ledger balance, not a column

`merchant_deposit` is an account kind on the existing double-entry ledger
(debit-normal, like `user_wallet`), owner `("merchant", merchant_id, "USD")`.
"Available to spend" is the NORMAL_SIDE-signed posting sum — one source of
truth, and two concurrent orders cannot overdraw it (the same argument as
ADR-0061's partner balances). The spec's §7 posting table is written in the
opposite sign convention; **the repo's convention is binding**: credit =
`D merchant_deposit / C house_payments_received`, charge is the exact mirror
(mirroring `payments/gateways/wallet.py`).

The 0067 downgrade deletes whole merchant-touching transactions —
counter-legs included, so surviving books keep `SUM(D) == SUM(C)`. Leg-only
deletion (what 0056 did) leaves one-legged transactions; 0067 corrects that
precedent.

### 3. Wholesale pricing has one home

`modules/merchants/pricing.py` owns
`price = ceil_to_cent(cost × (1 + (sku.b2b_markup_pct + adj) / 100))` —
`Decimal`, `ROUND_CEILING` to the cent (down-rounding erases margin on cheap
SKUs). `effective_cost()` is the single seam a future multi-supplier project
replaces. The **only** sanctioned copy is the admin SPA's labelled BigInt
preview (`features/catalog/b2b.ts`) — float ceilings genuinely diverge
(8.20 × 1.10 → 9.03 in float64 vs the correct 9.02), which is why the copy is
integer math with trap-case tests. Three copies of a currency helper drifting
apart (the `uzsWord` incident) is the standing reason for the rule.

No DB CHECK bounds `b2b_markup_pct`; the money guard is the order-time margin
floor (`merchant_margin_floor_pct`). A write-time bound would duplicate
policy and block legitimate below-retail corrections.

### 4. `active` was not renamed; `visible_b2b` sits beside it

`active` already IS retail visibility; renaming it to `visible_retail` (spec
§6's wording) would have touched every call site for cosmetics. The pairing
is documented on both models; effective B2B visibility =
`brand.visible_b2b AND sku.visible_b2b`.

## Consequences

- M2's order path debits the deposit through the same `post()` with the
  documented mirror legs; the README posting table is the contract.
- M2 must add the `(merchant_id, idempotency_key)` partial UNIQUE on orders
  before `merchant_order_id` idempotency leans on it (recorded in the M1
  progress ledger).
- The constraint-naming double-prefix footgun and its two valid migration
  patterns are documented at `core/db.py`; migrations 0066 and 0067
  demonstrate one each — they are deliberately opposite, not inconsistent.
