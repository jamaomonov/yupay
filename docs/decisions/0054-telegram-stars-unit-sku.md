# 0054. Telegram Stars as a unit SKU

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: @jamaomonov
- **Tags**: backend | catalog | orders | fulfillment | pricing | frontend
- **Supersedes (Telegram Stars only)**: [ADR-0053](./0053-price-a-free-amount-from-the-packages.md) tier
  pricing, the Stars use of `units_per_usd` from [ADR-0052](./0052-g-engine-as-a-second-source.md),
  and package SKUs as the source of the price

## Context and problem statement

Telegram Stars sold two ways at once: eleven package SKUs, each with its own
margin, plus a `tg-stars-any` variable-amount line. Because the margins
differed per pack, a typed amount could not be priced from a rate of its own —
ADR-0053 priced it from the package it fell in, with a monotonicity cap so 499
never cost more than 500. The storefront converted stars ↔ dollars through
`units_per_usd` (ADR-0052, migration 0047), and checkout, the display layer and
the G-Engine adapter each reversed a different piece of that conversion.

All of that machinery exists to keep the tiles and the free-amount field
agreeing under **per-pack volume discounts**. The volume discounts are gone. A
single sell rate per star is now the product: cost from the supplier (refreshed
hourly from G-Engine's `unfixed` rate), a percentage margin (ADR-0050), and an
optional per-currency override that already is the sell price of one star.
Packages are presets of that rate, not catalog rows.

Keeping the old model would leave two price sources and two checkout paths for
one rate — see "Why not keep the current model" below.

Steam is out of scope. Its `variable_amount` path (`amount_usd` × guarded FX ×
`rate_multiplier`, ADR-0032) does not change.

## Decision drivers

- One rate must price both the grid and the typed amount, by construction and
  not by two code paths agreeing.
- Deactivating eleven SKUs and flipping the twelfth is a **prod data change** on
  a live product. It must be reversible and it must not be coupled to a deploy.
- Raising the checkout quantity ceiling is a fraud surface: `qty` currently caps
  at 100 for every product in the catalog, and Stars needs 2500.
- `qty=500` must buy 500 stars once, never 500 fulfillments (the ADR-0032 trap:
  fulfillment creates exactly one `FulfillmentTask` per `OrderItem`).
- Old package SKUs must stay in the database — historical `order_items` point at
  them.

## Considered options

1. **A unit SKU priced per star, bought by `qty`** — one active SKU whose
   `cost_usdt` / `price_usd` / `price_overrides` are all per star, integer
   `min_qty` / `max_qty` bounds, and a checkout body of `{ sku_id, qty }`.
2. **Keep the variable-amount shape and re-point it at a per-star rate** — reuse
   `amount_usd`, `min_amount_usd` / `max_amount_usd` and `units_per_usd`, drop
   only the tier lookup.
3. **Keep the package SKUs and add a twelfth "1 star" SKU** — let the grid stay
   in the catalog and let the free amount be `qty` of the unit row.

## Decision outcome

**Chosen option:** Option 1. Product `telegram-stars` keeps a single **active**
SKU — the existing `tg-stars-any` row, no longer `variable_amount` — where the
unit is one star:

| Field                 | Meaning                                                             |
| --------------------- | ------------------------------------------------------------------- |
| `cost_usdt`           | Wholesale of 1★, hourly from the G-Engine `unfixed` rate            |
| `margin_percent`      | Drives `price_usd = cost × (1 + margin/100)` on refresh, as any SKU |
| `price_usd`           | Sell price of 1★ in USD                                             |
| `price_overrides`     | Sell price of 1★ in UZS/RUB/… — an already-with-margin course       |
| `amount_unit`         | `"Stars"` — storefront signal that the field and grid are in stars  |
| `min_qty` / `max_qty` | Inclusive integer bounds, in stars (new columns, migration 0049)    |
| mapping `quantity`    | `1` (per-unit multiplier)                                           |

The signal that a SKU is sold by unit — Stars, and anything shaped like it
later — is: **not** `variable_amount`, and `amount_unit`, `min_qty` and
`max_qty` all set. That predicate has exactly one implementation,
`catalog.unit_sku.is_unit_sku`, and checkout, the display layer, the admin form
and the storefronts all read it rather than re-deriving it.

`units_per_usd` and `units` are unused (NULL) on this SKU. `units` was the
package face value ADR-0053 priced from; there are no packages in the catalog
any more.

### Why `qty`, not `amount_usd`

ADR-0032 chose `amount_usd` over `qty` for the Steam wallet and gave three
reasons. Two of them are about dollars, and neither applies to stars:

- **Cents.** A top-up amount is a two-decimal dollar figure (`$9.99`) with no
  representation in an integer `qty`. A star count is an integer by
  construction — G-Engine's `Quantity` parameter takes nothing else.
- **Order history reads as nonsense.** "37 × Steam $1" is not a thing a
  customer bought. "500 Stars" is exactly what they bought, and it is the
  natural rendering of `qty` on a unit SKU.
- **`qty` means something specific downstream.** This one is real and is
  addressed rather than dismissed — see the G-Engine section below.

Beyond not sharing Steam's problems, `qty` is the field that already means "how
many of this thing", so every consumer of an order line gets the right answer
without a special case: the line total is `qty × unit_price_usd` like every
other SKU, revenue reads it already, and `unit_price_usd` stays a _price_ rather
than becoming a face value the way it is on a variable line (ADR-0051,
ADR-0053).

The counterpart is enforced: `amount_usd` on a unit-SKU line is a 422 ("this
product has a fixed price"), because there is a real per-star `price_usd`. USD
sales _are_ allowed here, unlike Steam, for the same reason — a margin-bearing
USD price exists.

Option 2 (reuse `variable_amount`) was rejected because it keeps the whole
dollars-as-a-way-of-naming-a-count indirection — `_snap_to_unit`, the
`units_per_usd` round-trip, `unit_price_usd`-as-face-value — for a product that
has a genuine integer count and a genuine per-unit price. Option 3 was rejected
because it leaves the grid in the catalog: two price sources again, and eleven
rows to keep in step with one rate.

### Why `DEFAULT_QTY_MAX = 100` remains for non-unit SKUs

`OrderItemIn.qty` was `Field(ge=1, le=100)`. 2500 stars does not fit, so the
**wire** ceiling rose to `UNIT_QTY_WIRE_MAX = 50_000`.

Raising the wire ceiling alone would have let any client buy `qty=50000` of a
gift card or a game top-up. So the wire limit is deliberately **not** the real
limit. `catalog.unit_sku.assert_qty_allowed`, called from
`orders.service._resolve_line_unit_price` before any pricing happens, is the
second gate:

- a unit SKU is bounded by its own admin-configured `min_qty` / `max_qty`;
- **everything else stays capped at `DEFAULT_QTY_MAX = 100`**, exactly as
  before.

Keeping 100 as the default is what makes this change additive rather than a
catalog-wide loosening: no existing product's behaviour moved, and the 50 000
figure is a last-resort guard against a malformed request, not a business rule.
`test_a_fixed_gift_card_still_rejects_qty_over_100` is the security regression
that pins it.

### G-Engine: `Quantity = qty × mapping.quantity`

G-Engine's unfixed services want **one** recharge whose `Quantity` is the star
count. This is where "`qty` means something specific downstream" had to be paid
for.

`gengine._quantity_for` now computes:

```
Quantity = item.qty × mapping.quantity
```

which is what the G2B adapter has always done. For an ordinary package SKU both
factors are meaningful — checkout allows up to `DEFAULT_QTY_MAX` packs on one
line, so this is genuinely "packs bought × units per pack". A unit SKU has no
per-pack size and its mapping's `quantity` is pinned to `1`, so the product
collapses to `item.qty` alone: the customer's own count.

The thing that must never happen is `qty=500` meaning 500 fulfillments.
Structurally it cannot: fulfillment creates exactly one `FulfillmentTask` per
`OrderItem`, and the adapter sends the count as a parameter of a single create.
A regression test pins it anyway — checkout `qty=500` produces exactly one
G-Engine create with `Quantity=500`.

### Alembic is schema-only; the data change is a separate idempotent seed

Migration `0049_sku_min_max_qty` adds two nullable columns and adjusts two
CHECKs. It does **not** touch a single Stars row.

Flipping `tg-stars-any` and deactivating the eleven packs is a separate
idempotent seed script (`scripts/seed/2026-08-21_telegram_stars_unit_sku.py`,
the same shape as `2026-08-18_telegram_stars_any_amount.py`), run by hand after
the new image is live. The reason is the failure mode of the alternative: if the data
change rode in `upgrade()`, a deploy that migrated and then rolled back — or
migrated and failed its health check — would leave Stars with its packs
deactivated and code running that still expects them. The product would be
unsellable, mid-migration, with no operator in the loop.

Separating them also means the two halves can be verified independently:
migration 0049 leaves every existing row NULL and therefore changes nothing
observable, and the seed can be dry-run, re-run (it is idempotent), and reverted
(`--revert` reactivates the packs and restores `variable_amount`) without a
deploy. The seed also carries a guard the migration could not: it aborts if
`cost_usdt` on `tg-stars-any` is not already per-star, because a value still
stored per pack would otherwise be silently resold as the price of one star.

Rows are deactivated, never deleted: historical `order_items` point at the
package SKUs, and they stay visible in the admin for order archaeology.

The migration's `downgrade()` is unsafe while a unit-SKU row exists
(`amount_unit` set, `units_per_usd` NULL) — the revert seed must run first. The
migration docstring says so.

### The CHECK had to be relaxed, and how

`ck_skus_amount_unit_complete` (migration 0047) required `amount_unit` and
`units_per_usd` to be set together. The unit SKU needs `amount_unit = 'Stars'`
with `units_per_usd` NULL, so shipping the seed against the old constraint would
have raised an `IntegrityError` in prod and left the catalog half-flipped.

Migration 0049 therefore widens the constraint to three legal shapes, rather
than dropping it:

1. both NULL — every row that existed before ADR-0052;
2. both set, `units_per_usd > 0` — the ADR-0047 variable-unit shape;
3. `amount_unit` set with `units_per_usd` NULL **and `min_qty` set** — the unit
   SKU.

The third arm is gated on `min_qty` on purpose: `amount_unit` alone would mean a
SKU that names a unit with no way to price or bound it. A new
`ck_skus_qty_bounds_complete` enforces the bounds themselves as both-or-neither,
with `min_qty >= 1` and `max_qty >= min_qty`. Steam leaves both NULL.

### Dual-read until the seed runs

Between the deploy and the seed, both shapes of Stars exist in the database at
once — the variable `tg-stars-any` row and, once the seed runs, the unit SKU.
Checkout and `gengine._quantity_for` therefore **dual-read**, and in both the
variable-amount branch is checked _first_:

- a variable line with `units_per_usd` re-derives its count from the money
  actually charged, exactly as before;
- everything else takes `item.qty × mapping.quantity`.

This is what makes step 2 of the rollout meaningful: the new image can be
deployed and `/store/telegram-stars` confirmed still selling packs and a free
amount, before any data moves. The legacy branch is dead code once the seed has
retired `units_per_usd` from the mappings it replaces — post-seed every
mapping's `quantity` is 1 and `item.qty` is the whole story — but it is not
removed in this PR, because the whole point is that the old rows keep working
until an operator says otherwise.

### Storefront

The UI is unchanged — an amount field and a package grid. What changed is where
the grid comes from: it is a **frontend constant**
(`50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500`), filtered to
`[min_qty, max_qty]` and priced as `N × sku.display_price`. The API does not
return packages, and a tile outside the bounds is not rendered. `SkuOut` gained
`min_qty` / `max_qty` so the page can do that filtering.

Selecting a tile and typing a number produce the identical body,
`{ sku_id, qty: N }` — which is the property this whole redesign exists to get:
the grid and the field cannot disagree, because there is nothing left for them
to disagree about.

`tierPrice`, `toUsd` / `unitsPerUsd` for Stars, and the "this product has both
packages and a free amount" branching are gone from this product. Steam's
`VariableAmountCard` is untouched.

Order history renders a unit line's `display.denomination` as
`"{qty} {amount_unit}"` (`500 Stars`), not the SKU's generic "Любое
количество". `display.variable_amount` stays false so clients do not treat
`unit_price_usd` as a Steam face amount.

### Positive consequences

- One rate prices the tiles and the typed amount, by construction. The
  monotonicity cap, the band lookup and the "499 costs more than 500" class of
  bug have nothing left to be wrong about.
- A margin change is one admin edit on one SKU instead of eleven.
- Nothing downstream needed a special case: the line total, revenue, the FX
  snapshot and the fulfilment saga all read `qty` and `unit_price_usd` with
  their ordinary meanings.
- Every other product's quantity ceiling is exactly what it was.
- The prod cutover is an operator-run, idempotent, revertible script rather than
  a deploy-time data rewrite.

### Negative consequences

- The package grid is a frontend constant, so changing it is a deploy, not an
  admin edit. Two constants, in fact — `apps/web` and `apps/miniapp` each have
  one, and they have to be kept in step.
- The wire `qty` ceiling is now 50 000 for every product, and the only thing
  keeping that from being a real limit is a server-side call. It is covered by a
  named regression test precisely because deleting the call would not break
  anything else.
- The dual-read branch in checkout and in `gengine._quantity_for` is dead code
  the moment the seed runs, and will read as unexplained until someone removes
  it. It is documented in both docstrings.
- ADR-0053's mechanism — `skus.units`, tier pricing, the monotonicity cap — is
  still in the codebase for products that use it, but has no user on Stars.
- `price_usd` / `cost_usdt` on the unit SKU may need a one-shot rescale if they
  still hold a per-pack or per-dollar figure. The seed guards it; confirming
  against the live G-Engine unfixed rate before running in prod is still a human
  step.

## Validation

- `apps/api/tests/unit/test_unit_sku.py` — `is_unit_sku`, and both halves of the
  quantity gate (a unit SKU past 100 is fine; an ordinary SKU past 100 is not).
- `apps/api/tests/integration/test_checkout_unit_sku.py` — `qty=500` charges
  500× the per-star price on both the override and the FX path; `qty=49` /
  `qty=2501` are 422 against bounds 50–2500; `amount_usd` is 422; a USD sale is
  allowed; and `test_a_fixed_gift_card_still_rejects_qty_over_100`.
- `apps/api/tests/integration/test_catalog_variable_sku.py` — the CHECK
  constraints; `test_admin_catalog_routes.py` — the admin round-trip of
  `min_qty` / `max_qty` and the both-or-neither rule.
- `apps/api/tests/unit/test_gengine_fulfiller.py` — one create with
  `Quantity=500` for `qty=500`, the existing pack case (`mapping.quantity=250`,
  `qty=1` → `Quantity=250`) unchanged, and the zero-qty guard.
- `apps/api/tests/unit/test_order_display.py` — the line renders as
  `500 Stars`.
- `apps/web/src/lib/star-packages.test.ts`,
  `apps/miniapp/src/lib/star-packages.test.ts`,
  `apps/web/src/components/store/PurchasePanel.test.tsx`,
  `apps/miniapp/src/lib/orders.test.ts` — tile price is `N ×` the rate, tiles
  outside the bounds are omitted, Steam helpers unchanged.

The operational milestone is the rollout's step 4: one test purchase where tile
50 and a typed 50 both create **one** G-Engine order with `Quantity=50`.

## Alternatives considered (detail)

### Option 2 — keep `variable_amount`, re-point it at a per-star rate

Needs no new columns and no new predicate. Rejected: it keeps `amount_usd` as
the wire field for a quantity that is an integer, keeps `_snap_to_unit` and the
`units_per_usd` round-trip so the adapter can reverse-engineer a count the
client already knew, keeps `unit_price_usd` as a face value rather than a price,
and keeps the Steam-shaped 422s (`qty != 1`, no USD sales) on a product that has
a real per-unit USD price. It buys a smaller diff by leaving the indirection the
per-pack margins paid for, after the per-pack margins are gone.

### Option 3 — keep the package SKUs, add a "1 star" SKU

Rejected: the grid stays in the catalog, so there are still two price sources
for one rate, eleven rows an operator can leave stale, and the ADR-0053 tier
lookup still standing between them. It also does not answer where the free
amount's price comes from — which was the original problem.

## Why not keep the current model

The current model is the correct answer to per-pack margins. Those are gone.
Eleven SKUs plus tier pricing plus `units_per_usd` is two price sources and two
checkout paths for a single rate; this ADR replaces them with one row, one rate,
and one wire field.

## Follow-ups

- Run the seed and the runbook in prod
  (`docs/runbooks/telegram-stars-unit-sku.md`), then remove the dual-read legacy
  branches in `orders.service` and `gengine._quantity_for`.
- Settle the final package list before release; the eleven values above are the
  working set.

## References

- `docs/superpowers/specs/2026-08-21-telegram-stars-unit-sku-design.md` — the
  design spec this ADR records
- `docs/superpowers/plans/2026-08-21-telegram-stars-unit-sku.md` —
  implementation plan and the five-step rollout
- `docs/runbooks/telegram-stars-unit-sku.md` — the seed run and its rollback
- [ADR-0032](./0032-variable-amount-skus.md) — variable-amount SKUs; why the
  Steam amount is a field and not `qty`
- [ADR-0050](./0050-sku-margin-percent.md) — `margin_percent` and the hourly
  cost refresh
- [ADR-0051](./0051-pin-the-rate-an-order-was-priced-at.md) — what
  `unit_price_usd` means on a variable line
- [ADR-0052](./0052-g-engine-as-a-second-source.md) — G-Engine, unfixed
  services, `mapping.quantity` as `Quantity`, `amount_unit` / `units_per_usd`
- [ADR-0053](./0053-price-a-free-amount-from-the-packages.md) — tier pricing,
  superseded for Stars
- `apps/api/migrations/versions/0049_sku_min_max_qty.py`
- `apps/api/src/yupay/modules/catalog/unit_sku.py` — `is_unit_sku`,
  `DEFAULT_QTY_MAX`, `UNIT_QTY_WIRE_MAX`, `assert_qty_allowed`
- `apps/api/src/yupay/modules/fulfillment/suppliers/gengine.py` —
  `_quantity_for`
