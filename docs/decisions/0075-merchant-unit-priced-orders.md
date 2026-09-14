# 0075. Merchant orders carry a quantity, and the cent is rounded once

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: owner
- **Tags**: backend | payments

## Context and problem statement

`POST /merchant/v1/orders` had no quantity. `qty=1` was a constant in
`merchants.orders.place`, and the request body was `merchant_order_id`,
`sku_id`, `expected_price`, `fulfillment_data`.

That is right for a denomination — 60 UC is a thing you buy one of — and wrong
for a currency sold by the unit. Telegram Stars is one SKU priced per star, and
retail carries the count in `OrderItem.qty`, which the G-Engine fulfiller reads
as the number of stars to send. A merchant could therefore buy exactly **one
star per order**.

Worse, they would overpay for it. `pricing.merchant_price` rounded up to the
cent, which is the right instinct on a SKU costing dollars and a 29% surcharge
on one costing $0.015455:

|                    | cost     | +7%      | published | effective markup |
| ------------------ | -------- | -------- | --------- | ---------------- |
| one Star, before   | 0.015455 | 0.016537 | **0.02**  | **+29.4%**       |
| 1000 Stars, before | 15.455   | 16.537   | **20.00** | **+29.4%**       |
| 1000 Stars, now    | 15.455   | 16.537   | **16.54** | **+7.02%**       |

$0.02 is also above our own **retail** price of $0.0191, so the wholesale
offer was worse than walking into the shop. Measured 2026-09-15: one of 206
orderable B2B SKUs, and it was the cheapest one — the SKU an integrator
reaches for first when told to debug on a cheap order (spec §2).

## Decision drivers

- The owner's rule: we sell at cost plus a markup. A rounding step that turns
  7% into 29% breaks that rule while appearing to follow it.
- The distinction already exists in our model (`catalog.unit_sku.is_unit_sku`)
  and in the supplier's (G-Engine's FIXED / UNFIXED). Inventing a third
  vocabulary would be the expensive option.
- Nothing is integrated yet: 1 merchant, 1 key, 2 orders, 0 webhooks. The
  window to change this contract cleanly closes the day a reseller ships.

## Considered options

1. **Hide Stars from the B2B catalog.** One SQL statement, instantly correct,
   and it removes a product rather than selling it.
2. **Bundle SKUs (100 / 500 / 1000 Stars).** Catalog rows, no contract change;
   cost is then measured in dollars and the cent is noise. Rejected as the
   primary answer because it duplicates a row per size forever and still
   cannot price an arbitrary count.
3. **Quantity in the request, G-Engine's shape.** Chosen.
4. **Widen every price to six decimals.** Rejected: the contract's own rule is
   that a machine client must never be handed two shapes for one quantity, and
   a balance is not a per-unit rate.

## Decision

`/catalog` publishes `kind`, and the order body accepts `quantity`.

- **`kind: "fixed"`** — `price_usd` at the cent, no `quantity` (sending one is
  `422 quantity_not_accepted`).
- **`kind: "unit"`** — `unit_price_usd` at **six** decimals plus `unit`,
  `min_qty`, `max_qty`; `quantity` required (`422 quantity_required`) and
  bounded (`422 quantity_out_of_range`).

`expected_price` becomes the **order total** in both shapes. At `qty=1` that
is the number it always was, so a fixed-SKU integration is unaffected.

Three consequences worth stating, because each is a place this could have been
done wrong:

- **The cent is rounded once, on the total**, not on each unit. Rounding per
  unit and multiplying is precisely the $20-instead-of-$16.54 bug.
- **The order line keeps the rate, the deposit takes the money.**
  `order_items.unit_price_usd` is $0.016537 on an order that cost $16.54,
  because `qty` beside it is what fulfilment sends the supplier. Everything
  merchant-facing therefore reports `merchant_order_total(unit, qty)` or the
  ledger, never the line. `deposit.charged_for_order` already declared itself
  the authority on what was paid, for exactly this reason.
- **`quantity` joins the replay digest.** It is part of the intent: retrying
  `acme-417` with a corrected count is a new order, and answering it with the
  old one would deliver 100 Stars against a request for 1000 and report
  success.

Neither mismatch is defaulted. A missing quantity would sell one Star; an
ignored one would charge for a denomination the merchant believed they bought
ten of. Both are refusals.

## Consequences

- A fixed-SKU integration sees two new always-present nullable fields and is
  otherwise unchanged; `price_usd` is now `null` on a unit row, which is why
  `kind` exists to branch on.
- `variable_amount` SKUs (Steam Wallet, a USD amount against a guarded FX
  rate) stay out of the merchant catalog. Different pricing model, different
  risk; unit SKUs were what was actually blocked.
- The margin floor is now evaluated against `cost × qty`, which is what it
  meant at `qty=1` and keeps meaning at any quantity.
- Option 1 remains available as an immediate lever if a unit SKU ever needs to
  leave the B2B catalog in a hurry.

## References

- [ADR-0069](./0069-merchant-machine-api.md) — the contract this amends
- [spec §8.3, §9.1](../superpowers/specs/2026-09-06-merchant-b2b-design.md)
- `apps/api/src/yupay/modules/merchants/pricing.py` — `merchant_unit_price`,
  `merchant_order_total`
- `apps/api/src/yupay/modules/catalog/unit_sku.py` — the FIXED/UNFIXED test
