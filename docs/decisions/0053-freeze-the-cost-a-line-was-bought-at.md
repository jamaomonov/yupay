# 0053. Freeze the cost a line was bought at, on the order line

- **Status**: Accepted
- **Date**: 2026-08-24
- **Deciders**: @jamaomonov
- **Tags**: orders | pricing | stats | admin | security

## Context and problem statement

ADR-0051 pinned the _markup_ on the order line so that editing a SKU's margin
could not revalue orders already taken. It did not cover the other half of the
same sum: `Sku.cost_usdt`.

That column is not admin-edited, it is machine-edited. The hourly
`refresh_supplier_prices` job rewrites it whenever an upstream price moves — up
or down — and `supplier_price_history` records 7 205 such transitions, 6 023 of
them after the first order was placed. Reporting read the live column, so every
supplier price move silently re-priced every past sale of that SKU. A margin
figure for last week changed this week because a supplier moved, on orders long
since closed.

Measured on production before this change: 21 of 144 costed order lines
disagreed with the cost recorded against them in `supplier_price_history`,
understating margin by $2.63 of $119.47 — 2.2%, growing with every price move.

This surfaced while putting margin beside revenue on the admin overview, which
turned a background inaccuracy in one analytics tab into a headline number.

## Decision

Add `order_items.cost_usdt`, written at checkout from the SKU's cost at that
moment. Margin resolves cost in three steps, mirroring how ADR-0051 resolves
the rate:

1. the cost frozen on the line;
2. failing that, the cost `supplier_price_history` says was in force at
   `orders.created_at`;
3. failing that, the live SKU.

`NULL` on a variable-amount line is not an omission: its cost is the face value
the customer chose, which `unit_price_usd` already records.

**The column is internal and must never reach a response a customer can read.**
Order responses are public to the buyer — a guest needs only the order id and
their email — so a field added to `OrderItemOut` "for the admin view" would
ship our purchase price to every buyer. `OrderItemOut` lists its fields
explicitly and forbids extras, and `test_cost_never_leaves_the_building.py`
fails if that changes.

## Considered alternatives

**Look the cost up in the history table at report time, with no new column.**
No migration, and it corrects existing orders too. Rejected as the primary
mechanism because it makes every margin query carry a correlated subquery per
line — tolerable for the 24h dashboard, not for the analytics tab's 90-day
per-SKU grouping — and because it depends on history reaching back far enough,
which for the oldest rows it does not. Kept as step 2, where it runs only for
rows with no snapshot: a set that stops growing at deploy, and `CASE` does not
evaluate branches past the one that matched.

**Backfill the new column from history in the migration.** Rejected on the
principle ADR-0051 already set: a reconstructed cost written into the column
would be indistinguishable from one recorded at checkout. `NULL` means "not
recorded", and the resolution order says so out loud each time it is read.

**Leave it and document the approximation.** Rejected because the figure had
just been promoted to the overview, where it is read as fact rather than as a
trend line.

## Positive consequences

- An order's margin is a function of what it cost when it was bought, not of
  what the supplier charges today.
- `gross - margin == cost` holds through a price move, not only through a
  markup edit.
- Old rows improve too, via history, without a guess being written down as a
  fact.

## Negative consequences

- One more column on the checkout write path, and one more thing order
  creation has to get right. Mitigated by writing it where the SKU is already
  loaded, re-resolving nothing.
- Rows predating this column keep a correlated lookup. Bounded and shrinking in
  relevance, never in count.
- A cost column now sits one careless schema edit away from the buyer. Pinned
  by test rather than by convention.

## Follow-ups (2026-10-05)

- **A route switch re-freezes the cost.** The value frozen at checkout is the
  routed supplier's. When a task is moved — an admin reassign, or the
  inventory→supplier fallback — the line is bought from someone else at their
  price, so `fulfillment/cost_resnapshot.py` re-quotes it from the new supplier
  (the reassign screen's read-only lookup), falls back to that supplier's
  newest `supplier_price_history` row, and otherwise keeps the old cost with
  the reason written into the `route_switch` attempt payload. Variable-amount
  lines are not touched: theirs is written on delivery from the actual charge.
- **The business tab reads the same cost.** `stats/analytics/business.py`
  valued fixed lines against the live `Sku.cost_usdt`, the very thing this ADR
  stopped the orders report from doing, so the two disagreed and the tab
  re-valued past sales on every price move. It now uses
  `orders.revenue.fixed_cost_basis_expr` — frozen → history → live — and the
  multiplier frozen on the line for Steam.
