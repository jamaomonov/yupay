-- Open Honor of Kings, Bigo Live and Likee to resellers.
--
-- `2026-09-21_hok_bigo_likee_import.py` creates brands through
-- `catalog.admin_service.create_brand`, which sets no `visible_b2b` — and the
-- column's server default is `false` on both `brands` and `skus`. Effective
-- B2B visibility is `brand.visible_b2b AND sku.visible_b2b` (the comment on
-- both columns says so), so the three brands were live on yupay.uz and absent
-- from `/merchant/v1/catalog` the moment they were imported. Owner direction,
-- 2026-09-21: open them.
--
-- Both halves are flipped, because either one alone is a brand a reseller
-- still cannot see and an operator has to debug.
--
-- **`b2b_markup_pct` is deliberately untouched.** It is `NOT NULL` with a
-- server default of 7, so every SKU created by that import already carries 7%
-- — the same number the rest of the catalogue sits at. Setting it here would
-- be a pricing decision smuggled into a visibility change.
--
-- Scoped by brand slug rather than by `visible_b2b = false`, so re-running it
-- cannot sweep something an operator deliberately hid elsewhere.

BEGIN;

UPDATE brands
SET visible_b2b = true, updated_at = now()
WHERE slug IN ('honor-of-kings', 'bigo-live', 'likee');

UPDATE skus
SET visible_b2b = true, updated_at = now()
WHERE product_id IN (
  SELECT p.id
  FROM products p
  JOIN brands b ON b.id = p.brand_id
  WHERE b.slug IN ('honor-of-kings', 'bigo-live', 'likee')
);

-- Every SKU of all three, and a cost on each — a SKU with no cost is absent
-- from the price list rather than free, so "visible" without one is a brand
-- that still looks empty to a reseller.
DO $$
DECLARE
  brands_open int;
  skus_open int;
  no_cost int;
BEGIN
  SELECT count(*) INTO brands_open
  FROM brands WHERE slug IN ('honor-of-kings', 'bigo-live', 'likee') AND visible_b2b;
  IF brands_open <> 3 THEN
    RAISE EXCEPTION 'expected 3 brands open to B2B, found %', brands_open;
  END IF;

  SELECT count(*) INTO skus_open
  FROM skus s
  JOIN products p ON p.id = s.product_id
  JOIN brands b ON b.id = p.brand_id
  WHERE b.slug IN ('honor-of-kings', 'bigo-live', 'likee') AND s.visible_b2b;
  IF skus_open <> 31 THEN
    RAISE EXCEPTION 'expected 31 SKUs open to B2B, found %', skus_open;
  END IF;

  SELECT count(*) INTO no_cost
  FROM skus s
  JOIN products p ON p.id = s.product_id
  JOIN brands b ON b.id = p.brand_id
  WHERE b.slug IN ('honor-of-kings', 'bigo-live', 'likee')
    AND s.visible_b2b
    AND s.cost_usdt IS NULL;
  IF no_cost <> 0 THEN
    RAISE EXCEPTION '% opened SKUs have no cost and would be missing from the price list', no_cost;
  END IF;
END $$;

COMMIT;
