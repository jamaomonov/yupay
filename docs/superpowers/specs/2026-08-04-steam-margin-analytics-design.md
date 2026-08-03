# Design — Steam (variable-amount) margin in business analytics

**Date:** 2026-08-04
**Status:** Approved (brainstorm), focused fix
**Scope:** `apps/api/src/yupay/modules/stats/analytics.py` (business analytics margin) + tests

## Problem

The admin **Аналитика → Бизнес** margin (`gross_margin_usd`, `margin_pct`, the
per-brand and per-SKU `margin_usd`) is computed as `revenue − cost` where cost =
`Sku.cost_usdt`, counting **only rows whose `cost_usdt` is known**. Steam
wallet top-ups are **variable-amount** SKUs: they have `cost_usdt = NULL` (the
cost is dynamic), so every Steam order falls into `margin_unknown_units` and
contributes **zero margin** to the report. Operators see no margin for Steam.

## Domain model (confirmed with the operator)

For a variable-amount (Steam) order, the customer chooses `amount_usd` (the
dollars credited to the wallet). At checkout:

- `OrderItem.unit_price_usd = amount_usd` — the raw dollars credited. This is the
  **cost basis**: `amount_usd × fx_rate` is what we pay (the original, un-marked-up
  FX conversion).
- The customer is charged `amount_usd × fx_rate × rate_multiplier` (the markup is
  the SKU's `rate_multiplier`, always `NOT NULL` for variable SKUs per the
  `ck_skus_variable_amount_complete` constraint).

So, expressed the way the operator thinks (in the charge currency):

- **cost** = `amount_usd × fx_rate` (raw FX rate)
- **revenue** (customer price) = cost × `rate_multiplier`
- **margin** = revenue − cost = cost × (`rate_multiplier` − 1)

The analytics report is denominated in **USD**, where the `fx_rate` cancels out:

- cost (USD) = `unit_price_usd`
- revenue (USD-equivalent) = `unit_price_usd × rate_multiplier`
- **margin (USD)** = `unit_price_usd × (rate_multiplier − 1)`

## Decision

Compute Steam margin from the SKU's `rate_multiplier` instead of skipping it.
Classify each order-item row into three buckets (by `Sku.variable_amount`):

| Bucket                | Predicate                                       | revenue term (USD)                       | cost term (USD)        |
| --------------------- | ----------------------------------------------- | ---------------------------------------- | ---------------------- |
| **fixed, known cost** | `NOT variable_amount AND cost_usdt IS NOT NULL` | `qty × unit_price_usd`                   | `qty × cost_usdt`      |
| **variable (Steam)**  | `variable_amount`                               | `qty × unit_price_usd × rate_multiplier` | `qty × unit_price_usd` |
| **unknown**           | `NOT variable_amount AND cost_usdt IS NULL`     | — (counted in `margin_unknown_units`)    | —                      |

- **Multiplier source:** the SKU's **current** `rate_multiplier` (it is not
  snapshotted on the order). The report is already flagged `margin_approx=True`
  and the multiplier changes rarely; the exact historical multiplier is out of
  scope.
- **Margin (USD)** for a row = revenue term − cost term. For variable this is
  `qty × unit_price_usd × (rate_multiplier − 1)`; for fixed it is the existing
  `qty × (unit_price_usd − cost_usdt)`.

### Three call sites, same treatment

1. `_business_summary` (lines ~106–141): `known_rev` = fixed sell + variable
   marked-up sell; `known_cost` = fixed cost + variable raw dollars;
   `margin = known_rev − known_cost`; `margin_pct = margin / known_rev`;
   `margin_unknown_units` counts only fixed-without-cost rows.
2. `_top_brands` (lines ~217–219): per-brand `margin_usd` sum includes the
   variable term. NULL only when a brand's rows are all fixed-without-cost.
3. `_top_skus` (lines ~251–253): same, per SKU.

Implement the per-row margin as a SQL `CASE`:

```python
from sqlalchemy import and_, case

margin_expr = case(
    (Sku.variable_amount.is_(True),
     OrderItem.qty * OrderItem.unit_price_usd * (Sku.rate_multiplier - 1)),
    (Sku.cost_usdt.isnot(None),
     OrderItem.qty * (OrderItem.unit_price_usd - Sku.cost_usdt)),
    else_=None,   # fixed-without-cost -> excluded, keeps NULL-when-empty behavior
)
```

`func.sum(margin_expr)` skips the `else_=None` rows, preserving the existing
"NULL margin when a group has no costable rows" contract.

## Out of scope (unchanged; flagged)

- **GMV** (`Σ Order.total_usd`) and the displayed per-brand/per-SKU
  `revenue_usd` columns still use the raw `unit_price_usd` for Steam (the
  amount-basis, not the marked-up customer price). Redefining those would change
  a headline metric (GMV) retroactively; the operator asked only for the margin.
  If the displayed revenue should also reflect the markup, that is a separate,
  explicitly-decided change.
- `margin_approx=True` stays — the margin remains an approximation (current
  multiplier, no supplier-fee netting).

## Testing

- `apps/api/tests/` (find the existing business-analytics test): add a Steam case
  — seed a paid order for a `variable_amount` SKU (`rate_multiplier` e.g. 1.20,
  `cost_usdt=NULL`, `unit_price_usd=10`), assert `gross_margin_usd` includes
  `10 × (1.20 − 1) = 2.00` and that the SKU is **not** in `margin_unknown_units`.
  Keep an existing fixed-SKU-with-cost case passing, and a fixed-without-cost case
  still counted as unknown. Add per-brand/per-SKU margin assertions for a Steam
  SKU (non-NULL, correct value).
- Coverage: `stats` module gate.
