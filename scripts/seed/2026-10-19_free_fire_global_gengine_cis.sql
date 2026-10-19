-- Free Fire Global: stop selling what G-Engine cannot deliver to a CIS account.
--
-- G-Engine's Free Fire service (46) delivers only 110, 231, 583, 645, 1188, 2420
-- and 6900 Diamonds to accounts on the CIS and Middle East servers; anything
-- else answers `invalid_account`. The player check (G2B `freefire_global`)
-- accepts those accounts, so it cannot catch it. By 2026-10-19 the Global
-- region had six deliveries and none succeeded.
--
-- Turns off the SKUs only G-Engine supplies outside that list (25, 50, 4450
-- Diamonds, Evo Access 3D/7D/30D) and drops the G-Engine route from the
-- memberships that G2B also supplies, so those go through G2B.
--
-- Idempotent.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 < scripts/seed/2026-10-19_free_fire_global_gengine_cis.sql

BEGIN;

UPDATE skus s SET active = false, updated_at = now()
FROM products p, brands b
WHERE s.product_id = p.id AND p.brand_id = b.id
  AND b.slug = 'garena-free-fire'
  AND s.denomination IN ('25 Diamonds', '50 Diamonds', '4450 Diamonds',
                         'Evo Access 3D', 'Evo Access 7D', 'Evo Access 30D')
  AND s.active;

UPDATE sku_supplier_mapping m SET is_active = false, updated_at = now(),
  updated_by = 'seed-2026-10-19-ff-global'
FROM skus s, products p, brands b
WHERE m.sku_id = s.id AND s.product_id = p.id AND p.brand_id = b.id
  AND b.slug = 'garena-free-fire'
  AND m.supplier_slug = 'gengine'
  AND s.denomination IN ('Weekly Lite', 'Weekly Membership', 'Monthly Membership')
  AND m.is_active;

COMMIT;
