# 0051. Pin the rate an order was priced at, on the order line

- **Status**: Accepted
- **Date**: 2026-08-16
- **Deciders**: @jamaomonov
- **Tags**: orders | pricing | stats | admin

## Context and problem statement

For a variable-amount SKU (Steam wallet top-ups) the margin is not a separate
fee — it lives inside the rate the customer is quoted:
`display_rate = market_rate * sku.rate_multiplier` (ADR-0032). A $10 top-up at
a 1.13 multiplier and an 11 900 so'm market rate is charged ~134 380 so'm,
which is ~$11.30 of real money.

`OrderItem.unit_price_usd` stores the **face value the customer chose** — the
$10 of Steam credit — because that is what has to be sent to the supplier.
`Order.total_usd` is the sum of those. Neither is revenue, and reading them as
revenue is how a customer who paid ~$11.30 was reported as having spent $10,
and how GMV disagreed with the margin figure printed directly beneath it.

The immediate reporting bug was fixed by re-deriving the number
(`orders.revenue`, `qty * unit_price_usd * rate_multiplier`). But that reads
`rate_multiplier` from the **live SKU row**, which an admin can change from the
UI at any time. Change the Steam margin tomorrow and every historical order
silently revalues. An order's worth must not be a function of today's pricing
config.

The codebase already has a field that looks like it solves this —
`Order.fx_snapshot_id` — and it does not:

| Paid orders in production    | 36     |
| ---------------------------- | ------ |
| with no `fx_snapshot_id`     | 28     |
| …of which Steam-only         | **28** |
| Steam-only _with_ a snapshot | **0**  |

`_compute_total_charged` sets `fx_snapshot_id` only on the fixed-price,
non-override branch; the variable branch `continue`s before reaching it. The
rate is fetched and charged against, then discarded — precisely for the orders
whose value depends on it.

## Decision drivers

- An order's value must be reconstructible from the order itself, not from
  mutable catalog config.
- Pricing is decided **per line**: one order can mix a Steam line (a multiplier
  applies) with an override-priced voucher (no rate was involved at all). A
  single per-order rate would misattribute one of them.
- `unit_price_usd` is already snapshotted per line. The multiplier is the
  missing half of the same price — this is finishing an existing pattern, not
  inventing one.
- Support and chargeback work need a question answered that no stored data
  answers today: "what rate did we actually quote this customer?"
- Whatever we do must not fabricate history for the orders already taken.

## Considered options

1. **Fix `fx_snapshot_id` so the variable branch sets it too.** Rejected as
   insufficient on its own: it is a pointer to a shared per-`(base, quote)`
   row, recovered by matching on the exact rate value
   (`_snapshot_id_for_rate`), which returns `None` whenever the match fails. It
   is also per-order, so it cannot describe a mixed order. A value on the line
   is strictly more robust than a pointer from the header.
2. **Derive USD as `total_charged / rate_of_the_order`.** Rejected: undefined
   for override-priced lines (no rate participated) and for USD orders, and it
   folds `_round_to_payable`'s rounding into the basis, so the "USD value" of
   an order would depend on the payability rules of its currency.
3. **Store the resulting USD figure per order.** Rejected: it records the
   answer without the inputs. Any later correction to the formula becomes
   unauditable, and it still cannot say what rate the customer saw.
4. **Snapshot the applied multiplier and the market rate on the order line.**
   Chosen.

## Decision

Add two nullable columns to `order_items`, written once at order creation:

- `rate_multiplier` `NUMERIC(10, 4)` — the SKU markup actually applied to this
  line. Mirrors `Sku.rate_multiplier`, exactly as `unit_price_usd` mirrors
  `Sku.price_usd`.
- `fx_rate` `NUMERIC(20, 10)` — the guarded market USD→order-currency rate the
  line was priced against. Same precision as `fx_snapshots.rate`, which is
  where the value comes from.

Both are `NULL` when they do not apply, and the distinction carries meaning:

| Line kind                        | `rate_multiplier` | `fx_rate` |
| -------------------------------- | ----------------- | --------- |
| Variable-amount (Steam)          | the SKU's         | market    |
| Fixed price, converted via FX    | `NULL`            | market    |
| Fixed price, `SkuPrice` override | `NULL`            | `NULL`    |
| Any line on a USD order          | `NULL`            | `NULL`    |

`orders.revenue` prefers the snapshot and falls back to the live SKU only when
the snapshot is absent:

```
CASE WHEN order_items.rate_multiplier IS NOT NULL
       THEN qty * unit_price_usd * order_items.rate_multiplier   -- recorded
     WHEN skus.variable_amount                                    -- pre-migration row
       THEN qty * unit_price_usd * skus.rate_multiplier
     ELSE qty * unit_price_usd
END
```

**Rows written before this migration are deliberately left `NULL` — there is no
backfill.** Backfilling them from today's `Sku.rate_multiplier` would produce
exactly the numbers the fallback already produces, while destroying the one
thing that matters about the column: a non-`NULL` value is a fact recorded at
the time of sale. Stamping a guess into the same column makes every row
indistinguishable from a real record. `NULL` honestly means "not recorded, ask
the SKU" — and the fallback keeps those orders reporting exactly as they do
today.

`Order.fx_snapshot_id` is left as-is. It is now redundant for valuation but
still a valid audit pointer for the lines that set it; removing it is a
separate cleanup.

## Positive consequences

- An order taken from today on is valued from its own row. Editing a SKU's
  margin no longer rewrites history.
- "What rate did this customer get?" becomes answerable per line — useful for
  support and for the chargeback evidence pack (ADR-0044).
- The mixed-order case is correct by construction rather than by assumption.
- The margin/gross pair (`analytics.business._margin_expr` and
  `orders.revenue.charged_usd_expr`) can move to the snapshot together and stay
  each other's twin.

## Negative consequences

- Two more columns on the hottest write path in the app, and one more thing
  order creation has to get right. Mitigated by writing them where the rate is
  already in hand (`_compute_total_charged`), not by re-resolving anything.
- Orders placed before this migration keep their existing, approximate
  valuation forever. That is the honest state; it is recorded here rather than
  papered over.
- Two sources of truth (snapshot, live SKU) coexist until the last
  pre-migration order ages out of every report. The `CASE` above is the single
  place that resolves them.

## Follow-ups

- `fx_rate` is recorded but not yet shown anywhere. Surfacing it on the admin
  order page ("quoted at 13 438 so'm/$") is what turns it into the support
  answer described above; until then the value is only in the database.
- Recording each line's charge in the order currency would make `total_charged`
  decomposable per line, which reconciliation wants. Out of scope here.
- `_snapshot_id_for_rate`'s match-by-value lookup should be retired once
  nothing depends on `fx_snapshot_id`.
