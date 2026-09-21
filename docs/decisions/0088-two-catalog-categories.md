# 0088. The catalogue has two categories, and they are the two delivery mechanisms

- **Status**: Accepted
- **Date**: 2026-09-21
- **Deciders**: @jamaomonov
- **Tags**: data | frontend | backend

## Context and problem statement

`categories` carried three rows — `games` (16 brands), `gift-cards` (3) and
`subscriptions` (3) — and one table serves every surface: the storefront's
filter chips, the Mini App's Home chips, the reseller cabinet's sidebar and
`category_slug` / `category_name` on `GET /merchant/v1/catalog`.

Three problems with that split, in ascending order of how much they cost:

- **It is a shelf label, not a property.** "Игры" and "Подписки и сервисы"
  describe what the product is _about_. Nothing downstream branches on that.
- **Its edges were arbitrary.** Steam sat in «Игры» and IMO in «Подписки»,
  and neither placement followed from anything.
- **The thing a buyer actually acts on was not represented at all.** Either
  you type an account id and a balance lands on it, or you get a code back
  and redeem it. That decides what the order form asks for, what the delivery
  looks like, and what support answers when it goes wrong.

## Decision drivers

- One taxonomy for all four surfaces; a second one would be two things to
  keep in agreement.
- Whatever replaces it must be derivable from data we already hold, not from
  somebody's opinion per brand.

## Considered options

1. **Keep three, rename «Подписки и сервисы»** — cosmetic; the arbitrary edge
   between it and «Игры» stays.
2. **Two categories, split on delivery mechanism.**
3. **Two categories for resellers only**, storefront untouched — a second
   taxonomy beside the first.

## Decision outcome

**Chosen option: 2**, applied everywhere.

The split needed no invention: `products.kind` is already
`Literal["top_up", "voucher"]`, and measured against production on
2026-09-21 **no brand mixes the two** — all 16 `games` brands and all 3
`subscriptions` brands are `top_up`, and the 3 `gift-cards` brands are
`voucher`. So «Игры» + «Подписки и сервисы» _is_ the set of top-up brands,
exactly. The merge is a rename plus moving three rows.

`games` is renamed in place to `top-ups` rather than replaced, so sixteen
brands keep their `category_id`. `subscriptions` is deactivated rather than
deleted: `Category.active` already gates every public read, so `false` hides
it as completely as a DELETE would and leaves the row reversible.
`scripts/seed/2026-09-21_two_catalog_categories.sql` carries the statements
and the ordering constraint — `list_brands` filters
`Brand.active AND Category.active`, so the three brands move _before_ the old
category is switched off.

Option 3 was rejected on the grounds that made the whole change worth doing:
the reseller cabinet and the storefront read one table today, and the
mechanism they would be grouping by is the same mechanism.

### Positive consequences

- The category answers a question somebody has: what will reach my buyer.
- Every frontend was already data-driven off `GET /catalog/categories` and
  `category_slug`, so the interfaces followed with no code change.
- The published `category_slug` now has a closed two-value vocabulary, which
  is documented on the field and therefore branchable.

### Negative consequences

- `category_slug` changes value for 19 of 22 brands. It is published on
  `/merchant/v1/catalog`, so a reseller who hardcoded `"games"` sees
  `"top-ups"`. The field's own description has always said it mirrors the
  storefront and never promised a stable value, and the B2B surface is weeks
  old — but this is a real break, not a theoretical one.
- Brand-import seeds already applied name `games` or `subscriptions`. They
  are left as history and would now fail on a missing category if re-run,
  which is the safe direction. The one seed **not** yet applied
  (`2026-09-21_hok_bigo_likee_import.py`) is corrected in the same commit.
- «Игры» disappears as a word from the storefront, and it is a word people
  search for. The brand pages still carry it everywhere; only the shelf label
  changed.

## Validation

The seed ends with a `DO` block that refuses to commit unless exactly two
categories are active and no active brand sits in an inactive one. After
that, `GET /api/v1/catalog/categories` returns two rows and every surface
renders them without a deploy.

## References

- `apps/api/src/yupay/modules/catalog/models.py` — `Product.kind`
- `scripts/seed/2026-09-21_two_catalog_categories.sql`
