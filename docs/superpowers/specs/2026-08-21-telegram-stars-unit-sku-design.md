# Telegram Stars as a unit SKU

**Date:** 2026-08-21
**Status:** Accepted, implemented — see [ADR-0054](../../decisions/0054-telegram-stars-unit-sku.md)
**Scope:** Catalog + orders + G-Engine fulfillment + admin SKU form + web + Mini App
**Supersedes (Stars-only):** ADR-0053 tier pricing, the Stars use of ADR-0047 `units_per_usd`, package SKUs as the source of price

Steam is out of scope. Its `variable_amount` path (`amount_usd` × guarded FX ×
`rate_multiplier`) does not change.

## Problem

Telegram Stars is sold two ways at once: ~11 package SKUs with their own
margins, plus a `tg-stars-any` variable line. A typed amount is not priced from
a rate of its own — it is priced from the package it falls in (ADR-0053), with a
monotonicity cap so 499 never costs more than 500. The storefront converts
stars ↔ dollars through `units_per_usd`. Checkout, display, and G-Engine
`Quantity` each reverse a different piece of that.

That machinery exists to keep tiles and the free-amount field agreeing under
**per-pack volume discounts**. Volume discounts are gone. A single sell rate
per star is the product: cost from the supplier (hourly), a % margin, and an
optional per-currency override (“Цены в других валютах”) that already is the
sell price of one star. Packages are presets of that rate, not catalog rows.

## Decisions (from brainstorming)

- Volume discount is dropped. One rate prices tiles and the typed amount.
- One active SKU. Unit = 1 star. `cost_usdt`, `margin_percent` → `price_usd`,
  and `price_overrides` are all **per star**.
- Min/max are new integer columns `min_qty` / `max_qty` in stars, edited in
  admin. Not `min_amount_usd` / `max_amount_usd`.
- Checkout sends `{ sku_id, qty: N }`. No `amount_usd` on this line.
- Package grid is a frontend constant (working set below; final list lands
  before release). API does not return packages. A tile outside min/max is
  not rendered.
- Existing package SKUs are **deactivated**, not deleted (orders already
  point at them).
- Steam stays on `variable_amount`.

## Catalog

Product `telegram-stars` keeps a single **active** SKU, the existing
`tg-stars-any` row. It is **not** `variable_amount`.

| Field                 | Meaning                                                                  |
| --------------------- | ------------------------------------------------------------------------ |
| `cost_usdt`           | Wholesale of 1★, hourly from G-Engine `unfixed` rate                     |
| `margin_percent`      | Drives `price_usd = cost × (1 + margin/100)` on refresh, same as any SKU |
| `price_usd`           | Sell of 1★ in USD                                                        |
| `price_overrides`     | Sell of 1★ in UZS/RUB/… — already-with-margin course                     |
| `amount_unit`         | `"Stars"` — storefront signal: field + grid are in stars                 |
| `min_qty` / `max_qty` | Inclusive integer bounds in stars                                        |
| mapping `quantity`    | `1` (per-unit multiplier)                                                |

Signal that a SKU is sold-by-unit (Stars, and anything like it later):
**not** `variable_amount`, and `min_qty`/`max_qty`/`amount_unit` are all set.

CHECK `ck_skus_qty_bounds_complete`: both qty bounds null, or both set with
`min_qty >= 1` and `max_qty >= min_qty`. Steam leaves them null.

`units_per_usd` is unused on this SKU (null). `units` is unused (null) —
that column was the package face value for ADR-0053.

`ck_skus_amount_unit_complete` (migration 0047) required `amount_unit` and
`units_per_usd` together, which this SKU cannot satisfy. Migration 0049
widens it to three legal shapes rather than dropping it: both null; both set
with `units_per_usd > 0`; or **`amount_unit` set with `units_per_usd` null
when `min_qty` is set** — the unit SKU. The third arm is gated on `min_qty`
because `amount_unit` alone would name a unit with no way to price or bound
it.

Hourly refresh already writes `cost_usdt` and re-derives `price_usd` from
`margin_percent`. For the unfixed G-Engine service the stored cost **is**
the price of one star (not of a pack). An UZS override is **not** rewritten
by refresh — same as today: override is the operator’s pinned sell course.

## Checkout

Tile “500 Stars” and typing 500 are the same body:

```json
{ "sku_id": "<the unit sku>", "qty": 500 }
```

`amount_usd` on this line is a 422 (“this product has a fixed price”).
USD is allowed: there is a real per-star `price_usd`, unlike Steam.

Charge:

- display currency with an override → `qty × override`
- otherwise → `qty ×` FX(`price_usd`) (USD: `qty × price_usd`)

Validate `min_qty ≤ qty ≤ max_qty`, integer (qty already is). The Pydantic
ceiling `OrderItemIn.qty: le=100` is too small (2500★). Raise the **wire**
max to `50_000`. The SKU bounds are the real gate; other products keep
behaving as they do because their operators send `qty=1`.

`unit_price_usd` stored on the line is the **per-star** USD price at
checkout, not the line total. Line total is `qty × unit_price_usd` like
every other SKU. Revenue uses that already.

## Fulfillment (the ADR-0032 trap)

G-Engine unfixed services want one recharge with `Quantity` = stars.

Today `_quantity_for` uses `mapping.quantity` for non-variable SKUs (50, 100,
…) and reverse-engineers stars from `unit_price_usd × units_per_usd` for
the variable line.

After: for an unfixed mapping,

```
Quantity = item.qty × mapping.quantity
```

with `mapping.quantity = 1` that is the star count. **One** create, not
`qty` creates. This matches how G2B already does `item.qty * mapping.quantity`.

A regression test must pin: checkout `qty=500` → exactly one G-Engine create
with `Quantity=500`. `qty=500` must never mean 500 fulfillments.

## Storefront (web + Mini App)

UI unchanged: amount field + package grid.

`SkuOut` gains `min_qty` / `max_qty`. The page that sees `amount_unit` and
qty bounds on a **non**-variable SKU:

1. Treats the field as a whole number of stars (not dollars).
2. Builds tiles from a shared constant, filtered to `[min_qty, max_qty]`.
3. Prices each tile as `N × sku.display_price`.
4. Selecting a tile or typing N both checkout `{ sku_id, qty: N }`.

Working package list (final list before release):

`50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500`

`tierPrice`, `toUsd` / `unitsPerUsd` for Stars, and “this product has both
packages and a free amount” branching go away on this product. Steam’s
`VariableAmountCard` is untouched.

Order history: `display.denomination` for a unit SKU is `"{qty} {amount_unit}"`
(e.g. `500 Stars`), not the SKU’s generic “Любое количество”.
`display.variable_amount` stays false, so clients do not treat
`unit_price_usd` as a Steam face amount.

## Admin

The existing SKU form:

- cost 1★ + % + “Цены в других валютах” already match the model;
- add min/max stars (`min_qty` / `max_qty`);
- hide / ignore the Steam-only block (`variable_amount`, dollar bounds,
  `rate_multiplier`) when editing this SKU — or show qty bounds instead of
  dollar bounds when `amount_unit` is set.

Deactivated package SKUs remain visible in admin for order archaeology.
Operators do not create new package SKUs for Stars.

## Data migration

Idempotent seed (same shape as `scripts/seed/2026-08-18_telegram_stars_any_amount.py`):

1. Ensure `tg-stars-any` is active, `variable_amount=false`, `amount_unit=Stars`,
   `min_qty=50`, `max_qty=2500` (admin can edit after), mapping quantity=1
   to G-Engine service 72.
2. Set `active=false` on the other `telegram-stars` SKUs (the packs).
3. Do not rewrite historical `order_items`.

`price_usd` / `cost_usdt` on the unit SKU may need a one-shot rescale if they
still store “per pack” or “per dollar of stars”. After migration they must
be **per star**. Confirm against the live G-Engine unfixed rate before
running in prod.

## Error handling

| Case                                     | Behaviour                                                                    |
| ---------------------------------------- | ---------------------------------------------------------------------------- |
| `qty` outside SKU bounds                 | 422, same family as Steam’s amount bounds                                    |
| `amount_usd` sent                        | 422 fixed-price                                                              |
| FX down, no override in that currency    | SKU has no display price; checkout 502 / fail-closed like other FX sales     |
| G-Engine unfixed rate missing on refresh | cost unchanged (existing refresh behaviour), SKU stays sellable at last cost |
| Every package filtered out by min/max    | grid empty, field still works                                                |

## Testing (must exist)

- Catalog: CHECK + admin round-trip of `min_qty`/`max_qty`; storefront DTO
  exposes them; inactive packs are absent from the product payload.
- Checkout: `qty=500` charges `500 ×` per-star price (override and FX
  paths); `qty=49` / `qty=2501` 422 with bounds 50–2500; `amount_usd` 422;
  USD sale allowed.
- Fulfillment: one G-Engine create, `Quantity=500`.
- Storefront unit tests: tile price is `N ×` rate; tiles outside bounds
  omitted; Steam helpers unchanged.
- Display: order line denomination is `500 Stars`.

## Out of scope

- Changing Steam.
- Volume discounts / a discount table on the unit SKU.
- Admin-editable package lists (constant on the frontend).
- Deleting old package SKU rows.
- New ADR number is 0054, written in the same PR as the code.

## Why not keep the current model

The current model is the correct answer to per-pack margins. Those are gone.
Keeping eleven SKUs + tier pricing + `units_per_usd` would leave two price
sources and two checkout paths for one rate.
