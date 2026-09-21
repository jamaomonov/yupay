# 0089. The per-merchant markup wakes up, and the margin floor is checked when it is set

- **Status**: Accepted
- **Date**: 2026-09-21
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | payments

## Context and problem statement

`merchants.markup_adjustment_pp` has been on the row since M1 and dormant
since. `pricing.merchant_markup_pct` has always returned
`sku.b2b_markup_pct + (merchant.markup_adjustment_pp or 0)`, so the
arithmetic was live; nothing could write the column, and it was `NULL` for
every merchant. Every reseller therefore paid the same price, and giving a
large one a better rate meant editing a row by hand or not doing it.

The column is in **percentage points** and applies to the whole catalogue at
once. That is what makes it useful — one number, one negotiation — and also
what makes it dangerous: with the catalogue at `b2b_markup_pct = 7` and
`merchant_margin_floor_pct = 2`, `-5` is the edge and `-6` makes **every**
order that merchant places fail with `margin_floor`, one refused order at a
time, with nothing on their page saying why.

## Decision drivers

- A pricing control an operator can reach without psql.
- A mistake that is knowable at the moment it is made should be refused then,
  not discovered later through failed orders.
- The order-time floor must remain the authority; nothing here may weaken it.

## Considered options

1. **Write the column, no check.** Smallest change; ships the footgun.
2. **Bound the input** (say `-5..+50`). Arbitrary: correct only while every
   SKU sits at 7 %, and silently wrong for a SKU at 4 %.
3. **Check against the thinnest markup on sale to resellers, at write time.**
4. **Warn in the UI only**, accept anything.

## Decision outcome

**Chosen option: 3.** `PATCH /admin/merchants/{id}/markup` sets or clears the
adjustment. When the value is negative, `markup.set_markup_adjustment` reads
the smallest `b2b_markup_pct` among SKUs actually on sale to resellers
(`brand.visible_b2b AND sku.visible_b2b`, both active) and refuses with
`markup_below_floor` if `thinnest + adjustment < floor` — answering with the
thinnest markup, the floor, and **the lowest value that would work**, so the
fix is a number rather than an experiment. The admin renders that answer
instead of flattening it into a generic failure.

`null` clears the adjustment back to the catalogue price. It is kept distinct
from `0`, which computes the same price and records an operator deciding on
no discount.

The check is scoped to visible SKUs rather than the whole catalogue because a
markup on something a reseller cannot order is not a constraint on their
price. It takes no `merchant_id`: B2B visibility is uniform across merchants
by design (spec §8.3), and the day that stops being true, that function is
where the argument goes.

### Positive consequences

- A negotiated rate is a field an operator fills in, with a confirm that
  names the whole catalogue rather than echoing the digits back.
- The most likely mistake is refused at the keystroke, with the correction in
  the refusal.
- `markup_adjustment_pp` rides along on every merchant read, so the list can
  show who is not on the catalogue price.

### Negative consequences

- **It is a guard, not a guarantee.** The SKUs a merchant sees change: one
  imported tomorrow at a thinner markup can put a previously-fine adjustment
  under the floor. `quote.py`'s order-time check stays exactly where it is and
  remains the authority. Nothing warns retroactively.
- One extra `MIN()` over the catalogue on every negative save. It is an
  operator action measured in tens per year.
- The control is catalogue-wide by construction. A per-brand or per-SKU rate
  for one merchant is still not expressible, and this makes it _look_ like
  pricing is solved when only the blunt instrument is.

## Validation

Six integration tests: a stored discount that also surfaces on the list, a
refusal that names the lowest working value, that the floor binds on the
thinnest SKU rather than an average, that an invisible SKU does not bind,
that a surcharge is never refused, and that `null` clears. The decision is
wrong if an operator ever has to be told "set it back, orders are failing" —
the signal this was meant to prevent.

## References

- `apps/api/src/yupay/modules/merchants/pricing.py` — where the column is read
- `apps/api/src/yupay/modules/merchants/quote.py` — the order-time floor
