# 0053 — Price a free amount from the packages, not from a rate of its own

- Status: accepted
- Date: 2026-08-18
- Deciders: @jamaomonov

## Context

Telegram Stars sells eleven packages and a free-amount field. Until now both
were priced the same way — cost × a single margin — so they agreed to within the
cent that `price_usd` is rounded to.

That stops being true the moment margin varies by pack. The intent is 20% on the
small packs and less on the large ones, the ordinary volume discount. With one
rate on the free-amount line, a customer typing 2500 would be charged the 20%
price while the 2500 tile right above the field sold at 10% — the two disagreeing
most exactly where the discount is deepest, and in the shop's favour, which is
the worst direction for it to be wrong in.

Unrounding `price_usd` was considered and rejected: the hourly supplier price
refresh re-derives it as `cost × (1 + margin)` and quantizes to cents, so any
unrounded value silently comes back rounded on the next tick.

## Decision

A package records how many units it delivers (`skus.units`, migration 0048), and
a free amount is priced **from the package it falls in**: 50–74 stars at the
50-pack's per-star price, 75–99 at the 75-pack's, and so on. One is derived from
the other, so they cannot disagree whatever the margins are.

Two rules, and the second is the one that is easy to miss:

1. The band is the largest package at or below the amount.
2. **An amount never costs more than the next package up.** Band pricing alone is
   not monotonic: with a 10% discount on the 500-pack, 499 stars at the 100-pack's
   rate came to $9.23 while 500 cost $8.89, so buying less cost more. The cap
   flattens the top of each band, which is monotonic and resolves in the
   customer's favour. A test asserts totals never decrease.

`units` is the mapping's `quantity` — the same number the adapter sends the
supplier as `Quantity` — so the price cannot be derived from a different figure
than the one that decides what the customer receives.

### Why the stored value is a face value, not the price

`unit_price_usd` on a variable line has always been a face value: the charge is
`face × rate × multiplier`, and revenue is `face × multiplier` (ADR-0051). The
tier price is therefore **divided** by the SKU's multiplier before it is stored,
and multiplied back downstream, leaving the customer charged exactly the package
price.

The alternative — storing the tier price raw and requiring `rate_multiplier = 1`
on these SKUs — was rejected because it makes correctness depend on a data field
nobody would think to check: a multiplier left at 1.2 would charge the margin
twice, silently, on every free-amount sale. Dividing makes a mis-set multiplier
cancel out instead of compounding. A parametrised test pins the charge at the
package price for multipliers 1, 1.2 and 1.5.

## Consequences

### Positive

- Free amount and packages agree exactly, at every tier, under any margins.
- Per-pack margins become an ordinary admin edit (`margin_percent` per SKU) with
  no second place to keep in sync.
- Nothing downstream changed: revenue, analytics and the FX snapshot still read
  `unit_price_usd × rate_multiplier`, which still means the same thing.
- No rate needs to be shown to the customer — there no longer is one.

### Negative

- Checkout eager-loads the product's other SKUs (one extra query per checkout,
  not one per line).
- A product with a free amount but no packages keeps billing the amount as named;
  that is the Steam wallet, and it is the documented fallback rather than an
  oversight.
- The bands are invisible to the customer. Typing 499 and paying the 500 price
  is in their favour, but it is not explained anywhere on the page.

## Follow-ups

- Set the intended per-pack margins (20% small → 10% large). The mechanism is in
  place; the numbers are a business decision.
- Consider surfacing "you'd pay the same for 500 — take 500" when the cap binds.
