-- scripts/seed/2026-08-18_stars_units.sql
--
-- Tell each Telegram Stars package how many stars it delivers, so the
-- free-amount line can be priced from the packages (migration 0048).
--
-- The number is taken from `sku_supplier_mapping.quantity`, which is what the
-- adapter already sends to G-Engine as `Quantity` — so this cannot disagree
-- with what the customer actually receives. Deriving it from the SKU code or
-- from cost would both be guesses that go wrong the moment a rate moves.
--
-- The variable line itself keeps `units = NULL`: its amount is typed, not fixed.
--
-- Idempotent: re-running writes the same values.

BEGIN;

UPDATE skus s
SET units = m.quantity
FROM sku_supplier_mapping m
WHERE m.sku_id = s.id
  AND m.supplier_slug = 'gengine'
  AND m.is_active
  AND s.variable_amount = false
  AND s.sku_code LIKE 'tg-stars-%'
  AND m.quantity > 0;

-- Report what happened, so an operator running this by hand sees it.
SELECT s.sku_code, s.units, s.price_usd,
       round(s.price_usd / s.units, 6) AS usd_per_star
FROM skus s
WHERE s.sku_code LIKE 'tg-stars-%'
ORDER BY s.units NULLS LAST;

COMMIT;
