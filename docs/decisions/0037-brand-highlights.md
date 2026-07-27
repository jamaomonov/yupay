# 0037. Brand highlights (localized value-prop chips)

- **Status**: Accepted
- **Date**: 2026-07-27
- **Deciders**: @jamaomonov
- **Tags**: backend | catalog | frontend

## Context and problem statement

The upcoming Steam "0% commission" storefront section (see
`docs/superpowers/specs/2026-07-27-steam-zero-commission-design.md`, layer B)
needs a handful of short, punchy value-prop chips on the brand hero — "0%
комиссии", "Оплата в сумах", "1–3 минуты" — that a customer can scan in under
a second before reading anything else on the page. This is the first task in
a short chain (backend field → frontend rendering → seed data) building that
section.

The obvious shortcut is to hardcode Steam's three chips as a constant in the
frontend, keyed off `brand.slug === "steam"`. That fails the moment any other
brand (PSN, a future variable-amount product, a promo-driven brand) wants the
same treatment: it would need a code change and a redeploy, not a content
edit, and it can't be localized per the existing `ru`/`en`/`uz` pipeline.

## Decision drivers

- AGENTS.md §11: never hardcode user-facing strings; every new key goes
  through the `ru`/`en`/`uz` translation pipeline. A slug-keyed frontend
  constant embeds untranslated Russian directly in TSX.
- `BrandDetailOut` already localizes `name`/`short_description`/
  `description`/`instructions` via `_pick_translation` with a `DEFAULT_LOCALE`
  ("ru") fallback (ADR-0009, `apps/api/migrations/versions/0022_brand_instructions.py`)
  — highlights should read the same way to a client, not introduce a second
  localization shape.
- `_pick_translation`'s 4-tuple return type is depended on by the product
  translation path too (`_build_product_summary` calls it with a
  `ProductTranslation` list, which has no `highlights` column at all).
  Widening it to a 5-tuple would force every caller — including product
  summaries, which have no use for `highlights` — to unpack and discard a
  field that's meaningless for them.

## Considered options

1. **New nullable `highlights` JSON column on `BrandTranslation`, read by a
   dedicated `_pick_highlights` helper** — reusable across any brand,
   content-editable without a deploy, localized like every other brand field.
2. **Hardcode the chips in the frontend, keyed by brand slug** — fastest to
   ship for Steam alone, but violates the i18n rule above and doesn't
   generalize to the next brand that wants the same treatment.
3. **Widen `_pick_translation`'s return tuple to include `highlights`** —
   keeps everything in one function, but leaks a brand-only field into the
   shared product-translation code path and changes a signature every
   existing caller (including `_build_product_summary`) already depends on.

## Decision outcome

**Chosen option:** Option 1. `BrandTranslation.highlights` is a nullable
`JSON` list of strings (SQLAlchemy's generic `JSON` type, not `JSONB` —
portable across the SQLite/Postgres split between the test harness and
production, matching how the rest of this column is meant to be read: small,
infrequently-written, never queried by content). `NULL`/absent means "render
no chips" — there is no empty-list-vs-null distinction the frontend needs to
care about, since `catalog.service._pick_highlights` always normalizes to a
list.

`_pick_highlights` is a standalone function next to `_pick_translation`,
not a change to it, but it resolves the **same way**: row-level fallback,
identical in shape to `_pick_translation`'s `(translations, locale,
fallback=...)` signature and its `by_locale.get(locale) or
by_locale.get(fallback) or translations[0]` selection. It falls back to the
`DEFAULT_LOCALE` row only when the requested locale has **no translation row
at all** (e.g. a brand never translated into `uz`). If the row for the
requested locale exists but its `highlights` happens to be `NULL` — a brand
translated into `en` before anyone wrote English chips — it returns `[]`,
not the `ru` row's chips. Consistency with `_pick_translation` was chosen
over per-field leniency: bleeding `ru`-language marketing chips onto an
`en`-rendered page is a worse failure mode than showing no chips, the same
i18n-safety judgment that already governs `description`/`instructions`, and
a reader who already knows `_pick_translation`'s row-level rule gets
`_pick_highlights` for free instead of having to learn a second rule.

`BrandDetailOut.highlights: list[str]` defaults to `[]` via
`Field(default_factory=list)`, matching the existing `faqs` field's shape.

### Positive consequences

- Any brand can get hero chips through the existing admin brand-translation
  edit flow (once Task 4's seed/admin wiring lands) — no code change, no
  redeploy, no slug-keyed special case.
- `highlights` is read off `Brand.translations`, already eagerly loaded via
  `selectinload(Brand.translations)` in `get_brand_by_slug` — zero additional
  queries, no N+1.
- `_pick_translation`'s signature and the product-translation call sites are
  untouched.

### Negative consequences

- A brand can be fully translated into a locale (name, description,
  instructions all present) yet show zero hero chips on that locale if only
  `highlights` was left unfilled for it — an editor filling in `en` copy has
  to remember to add `highlights` too, or the `en` page silently loses the
  chip band even though the `ru` page has one. Acceptable: this is the same
  trade-off `description`/`instructions` already make, and a missing chip
  band degrades gracefully (the hero still renders without it).
- `JSON` (not `JSONB`) means Postgres cannot index or query into the chip
  list. Acceptable: highlights are always read whole, never filtered by
  content.

## Validation

`apps/api/tests/integration/test_catalog_routes.py::test_brand_detail_returns_localized_highlights`
(locale match; a locale row that exists with `highlights=NULL` returns `[]`,
no bleed from `DEFAULT_LOCALE`; a locale with no translation row at all falls
back to the `DEFAULT_LOCALE` row) and `::test_brand_detail_highlights_default_empty`
(no translation has `highlights` set anywhere -> `[]`, not `None` or a 500).

## Alternatives considered (detail)

### Option 2 — hardcode in the frontend

Ships fastest for exactly one brand, but the copy would be un-translatable
Russian baked into TSX, and every future brand wanting the same chips repeats
the special case. Rejected outright — this is the exact shape AGENTS.md §11
exists to prevent.

### Option 3 — widen `_pick_translation`

Keeps localization logic in one function, but `_pick_translation` is called
from `_build_product_summary` and `_brand_summary` with `ProductTranslation`
rows that have no `highlights` column — every caller would need to unpack and
ignore a 5th field that's meaningless outside the brand-detail path. A
separate `_pick_highlights` keeps the blast radius to the one call site that
actually wants it.

## References

- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — catalog
  three-level model, brand/product translation shape
- `apps/api/src/yupay/modules/catalog/models.py` —
  `BrandTranslation.highlights`
- `apps/api/migrations/versions/0032_brand_highlights.py`
- `apps/api/src/yupay/modules/catalog/service.py` — `_pick_highlights`,
  `get_brand_by_slug`
- `docs/superpowers/specs/2026-07-27-steam-zero-commission-design.md` — the
  feature this field was built for (layer B)
