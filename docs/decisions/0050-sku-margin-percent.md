# 0050. Persist a SKU's margin so cost refresh cannot sell below cost

- **Status**: Accepted
- **Date**: 2026-08-13
- **Deciders**: @jamaomonov
- **Tags**: catalog | integrations | admin

## Context and problem statement

The hourly supplier price-refresh (`integrations.price_refresh`, since the
original `refresh-all-prices` job) updates `Sku.cost_usdt` from G2B and posts a
Telegram alert on any move past a threshold. It has never touched
`Sku.price_usd`. That split was fine while the two moved together by
coincidence; it stops being fine the moment a supplier raises a price on a SKU
nobody is actively re-pricing. Sell at $12 on a $10 cost, watch the supplier's
price climb to $13, and the shop is now selling at a $1 loss on every order —
silently, with only a Telegram line nobody read as a loss warning.

`margin_percent` did not exist as a stored fact. The admin SKU form already
computed it live from `price_usd` and `cost_usdt` for editing convenience
(two-way sync: change one, the other recalculates), but it lived in component
state and was never sent to the backend — recomputed fresh from whatever
`price_usd`/`cost_usdt` happened to be, never asserting what margin the SKU
was actually _meant_ to hold.

## Decision drivers

- Selling below cost is a real-money loss per order, not a display glitch —
  the failure mode that matters most is a SKU nobody is watching.
- The point is specifically to protect SKUs nobody is actively re-saving —
  waiting for an admin to open and re-save each one first defeats it.
- Existing behaviour (cost updates, price doesn't) must survive unchanged for
  a SKU that genuinely has no margin on file — no surprise price movement on
  something an admin deliberately priced without a formula in mind.
- The G2B game-import wizard already established the formula and its
  rounding (`_sell_price` in `integrations.service`, `ROUND_HALF_UP` to
  cents) for a _request-time_ margin. This reuses it for a _persisted_ one.

## Considered options

1. **Compute margin on the fly wherever needed**, same as the admin form did —
   never store it.
2. **A nullable `Sku.margin_percent` column**, filled from the form and read by
   the refresh job to re-derive `price_usd` when `cost_usdt` moves.
3. **Alert-only**: keep cost-only updates, make the existing Telegram alert
   louder/keyword-flagged when the implied margin would go negative, and
   leave the price correction to a human.

## Decision outcome

**Chosen option: 2.**

Option 1 cannot protect a SKU nobody is looking at — the whole point is
SKUs nobody is actively re-saving. Option 3 still lets an order sell at a
loss during the gap between the alert firing and someone acting on it, on a
line business-critical enough that the gap itself is the risk.

**`margin_percent` is nullable, `NULL` is a real state, not a gap to fill
in later**: no margin on file → refresh updates `cost_usdt` only, exactly
the pre-existing behaviour. A margin only ever gets attached by an admin
interacting with the SKU form (typing a margin, a price, or a cost — all
three keep each other in sync and all three now persist) or by the
migration backfill below.

**Backfilled from the current price/cost ratio, not left NULL, on
migration.** The feature exists to protect SKUs nobody is actively
re-saving — requiring a re-save first to get any protection would cover
almost nothing at launch. `ROUND(((price_usd - cost_usdt) / cost_usdt) *
100, 4)` runs once, in the migration, for every row with a positive
`cost_usdt`; rows with no cost on file get no ratio to compute and stay
`NULL`, identical to their refresh behaviour today.

**Price is only re-derived on an actual cost move**
(`set_sku_cost_usdt` in `catalog.admin_service`), never on every refresh
tick — an unchanged cost has nothing new to protect against, and touching
`price_usd`/`updated_at` on a no-op would be a false "something changed"
signal on the SKU list and in `updated_at`-driven caches.

**A candidate price that would round to ≤ 0 is silently skipped, cost
still writes.** Reachable only when a saved margin is at or near -100%
(the schema/DB constraint refuse -100 exactly, but e.g. -99.99% on a small
cost can still round to $0.00 at cents precision) — refuse to write a price
`ck_skus_price_positive` would reject anyway, without crashing the refresh
tick over one pathological SKU.

**The Telegram alert grows a price line, only when price actually moved**:
"Цена USD: $12.00 → **$15.60** (наценка 20% сохранена)", appended after the
existing cost line. A SKU with no margin gets no such line — the alert stays
exactly as terse as it always was for the majority of SKUs.

### Negative consequences

- A margin now persists the instant an admin saves _any_ edit to a SKU that
  has both `price_usd` and `cost_usdt` set, not just an explicit margin
  edit — opening an old SKU to fix a typo in its denomination and hitting
  Save also locks in whatever ratio was already implicitly there. Treated as
  acceptable: that ratio was already the real, in-effect margin; recording it
  is making an existing fact explicit, not inventing one. Flagged here for
  the next maintainer who wonders why an unrelated edit changed
  `margin_percent`.
- `set_sku_cost_usdt`'s return type changed from `Decimal | None` to a
  `CostUpdateResult` dataclass. Contained to its one caller
  (`integrations.service.refresh_sku_cost_for_mapping`).

## Validation

- `test_sku_cost_margin.py`: margin set + cost moves → price recomputed to
  the cent; margin set + cost unchanged → nothing recomputed; no margin →
  price untouched (pre-existing behaviour, pinned); a margin that would zero
  the price → skipped, cost still writes.
- `test_integrations_price_refresh.py`: the same two branches end-to-end
  through the G2B-mocked refresh pipeline, including asserting the Telegram
  payload contains (or omits) the new price line.
- `test_admin_catalog_routes.py`: `margin_percent` round-trips through
  `POST`/`PATCH /admin/catalog/skus`, stays absent from the public
  `GET /catalog/skus/{id}`, and a margin ≤ -100% is a 422 before it ever
  reaches the DB constraint.
- Verified live against the dev DB: bumped a real SKU's cost from $9 to $10
  through `set_sku_cost_usdt` directly (bypassing G2B) with a 20% margin on
  file — `price_usd` moved from $10.80 to $12.00, confirmed both via `psql`
  and reloading the admin SKU page.

## References

- `apps/api/migrations/versions/0043_sku_margin_percent.py` — column, check
  constraint, backfill.
- `integrations.service._sell_price` — the request-time formula this reuses
  (duplicated, not imported, to avoid a `catalog` ↔ `integrations` cycle; see
  that module's README).
