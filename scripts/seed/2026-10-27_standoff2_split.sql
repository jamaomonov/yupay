-- scripts/seed/2026-10-27_standoff2_split.sql
--
-- Standoff 2 becomes two brands (owner, 2026-10-27):
--
--   standoff-2     promo codes (G-Engine vouchers) — the page with the search
--                  history. Back on, in `gift-cards`, for resellers too, but in
--                  MAINTENANCE: G-Engine has been down since 2026-10-08, so it
--                  takes no orders and points buyers at the by-id brand
--                  (`maintenance_redirect_id`, migration 0107).
--   standoff-2-id  Gold by player id, filled by hand — its own page and copy, in
--                  top-ups, storefront only (not the reseller catalogue).
--
-- Earlier the same day the by-id product had replaced the promo one on
-- `standoff-2`; this undoes that. Two brands because the reseller cabinet files a
-- brand under one category and `visible_b2b` is per brand. When promo codes come
-- back, the storefront can show both on one page the way MLBB / Free Fire regions
-- do; until then they are two pages.
--
-- Run order on prod, after the deploy that carries migration 0107:
--   1. this file
--   2. 2026-10-27_standoff2_by_id_seo.sql   (copy for standoff-2-id)
--   3. standoff2_seo.sql                    (promo copy back on standoff-2)
--   4. 2026-10-12_standoff_roblox_seo.sql   (promo search titles + price FAQ)
--
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -v ON_ERROR_STOP=1 -U yupay_app -d yupay < scripts/seed/<file>
--
-- Promo codes on sale again = one statement:
--   UPDATE brands SET maintenance = false WHERE slug = 'standoff-2';
--
-- Idempotent.

BEGIN;

INSERT INTO brands (id, slug, category_id, logo_url, hero_image_url, accent_color,
                    sort_order, active, visible_b2b, visible_retail)
SELECT gen_random_uuid(), 'standoff-2-id', ff.category_id, b.logo_url, b.hero_image_url,
       b.accent_color, b.sort_order, true, false, true
FROM brands b, brands ff
WHERE b.slug = 'standoff-2' AND ff.slug = 'free-fire'
ON CONFLICT (slug) DO NOTHING;

INSERT INTO brand_translations (brand_id, locale, name)
SELECT b.id, v.locale, v.name
FROM brands b, (VALUES
    ('ru', 'Standoff 2 по ID'),
    ('en', 'Standoff 2 by ID'),
    ('uz', 'Standoff 2 ID orqali')
) AS v(locale, name)
WHERE b.slug = 'standoff-2-id'
ON CONFLICT (brand_id, locale) DO NOTHING;

UPDATE products SET brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2-id')
WHERE slug = 'standoff-2-gold-id';

UPDATE brands SET
    category_id = (SELECT id FROM categories WHERE slug = 'gift-cards'),
    visible_b2b = true,
    maintenance = true,
    maintenance_redirect_id = (SELECT id FROM brands WHERE slug = 'standoff-2-id'),
    updated_at = now()
WHERE slug = 'standoff-2';

UPDATE products SET active = true WHERE slug = 'standoff-2-gold';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.slug = 'standoff-2-gold-id' AND b.slug = 'standoff-2-id'
    ) OR NOT EXISTS (
        SELECT 1 FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.slug = 'standoff-2-gold' AND b.slug = 'standoff-2' AND p.active
          AND b.maintenance AND b.maintenance_redirect_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'standoff 2 split did not land';
    END IF;
END $$;

COMMIT;
