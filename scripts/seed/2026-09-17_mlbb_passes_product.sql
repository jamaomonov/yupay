-- scripts/seed/2026-09-17_mlbb_passes_product.sql
--
-- Split the Mobile Legends "diamonds" product of each region into two:
-- diamonds proper, and the passes / packs that were mixed in with them
-- (Weekly Elite Pack, Weekly Diamond Pass, Monthly Elite Pack, Twilight Pass
-- on the global brand; Limited-Time Value Pack and Weekly Diamond Pass on the
-- RU one). The storefront and the mini app show a product switcher for a
-- brand with several products, so the customer picks «Алмазы» or «Пропуски и
-- наборы» first and then a package. Magic Chess: Go Go is left alone on
-- purpose — one pack per region does not justify a tab (owner, 2026-09-17).
--
-- The new products copy `required_fields` 1:1 from the diamonds product:
-- the player check is resolved per brand and refuses when a brand's products
-- disagree on their `check` config (ADR-0079), so a hand-edited copy would
-- switch the check off for the whole brand.
--
-- Also renames «Алмазы — глобальный / российский аккаунт» to plain «Алмазы»:
-- the region lives in the brand name since the split, and the product tabs
-- read «Алмазы | Пропуски и наборы».
--
-- SKUs move by sku_code; G2B mappings, sourcing rules and orders hang off the
-- SKU and do not move. Merchant Center offerIds are sku_codes — nothing is
-- deleted from the feed. Idempotent: product inserts are guarded by slug,
-- translations upsert, SKU moves are no-ops once done, and the sort_order
-- renumbering is stable. A no-op where the source products are absent.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. The two new products, copied from the diamonds product of the same brand.
-- ---------------------------------------------------------------------------

INSERT INTO products (id, slug, kind, supplier_hint, image_url, sort_order, active, brand_id, required_fields)
SELECT gen_random_uuid(), 'mlbb-passes', p.kind, p.supplier_hint, p.image_url, 1, p.active, p.brand_id, p.required_fields
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE b.slug = 'mobile-legends' AND p.slug = 'mlbb-diamonds'
  AND NOT EXISTS (SELECT 1 FROM products WHERE slug = 'mlbb-passes');

INSERT INTO products (id, slug, kind, supplier_hint, image_url, sort_order, active, brand_id, required_fields)
SELECT gen_random_uuid(), 'mlbb-passes-ru', p.kind, p.supplier_hint, p.image_url, 1, p.active, p.brand_id, p.required_fields
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE b.slug = 'mobile-legends-ru' AND p.slug = 'mlbb-diamonds-ru'
  AND NOT EXISTS (SELECT 1 FROM products WHERE slug = 'mlbb-passes-ru');

-- ---------------------------------------------------------------------------
-- 2. Names. New products get theirs; the diamonds products drop the region
--    suffix the brand name now carries.
-- ---------------------------------------------------------------------------

INSERT INTO product_translations (product_id, locale, name, short_description)
SELECT p.id, v.locale, v.name, v.short_description
FROM products p, (VALUES
    ('ru', 'Пропуски и наборы', 'Еженедельные и месячные наборы и пропуски — те же ID игрока и сервер.'),
    ('en', 'Passes & packs', 'Weekly and monthly packs and passes — same player ID and server.'),
    ('uz', 'Passlar va toʻplamlar', 'Haftalik va oylik toʻplamlar va passlar — oʻsha oʻyinchi ID va server.')
) AS v(locale, name, short_description)
WHERE p.slug IN ('mlbb-passes', 'mlbb-passes-ru')
ON CONFLICT (product_id, locale) DO UPDATE
    SET name = EXCLUDED.name, short_description = EXCLUDED.short_description;

-- The diamonds products' one-liners described the region ("для аккаунтов
-- Узбекистана и СНГ на глобальном регионе"); the brand page says that now,
-- so the line describes the product instead.
UPDATE product_translations t SET name = v.name, short_description = v.short_description
FROM products p, (VALUES
    ('mlbb-diamonds',    'ru', 'Алмазы',   'Алмазы номиналом от 55 до 9994.'),
    ('mlbb-diamonds',    'en', 'Diamonds', 'Diamonds from 55 to 9,994.'),
    ('mlbb-diamonds',    'uz', 'Olmoslar', '55 dan 9994 gacha olmoslar.'),
    ('mlbb-diamonds-ru', 'ru', 'Алмазы',   'Алмазы номиналом от 35 до 6000.'),
    ('mlbb-diamonds-ru', 'en', 'Diamonds', 'Diamonds from 35 to 6,000.'),
    ('mlbb-diamonds-ru', 'uz', 'Olmoslar', '35 dan 6000 gacha olmoslar.')
) AS v(slug, locale, name, short_description)
WHERE t.product_id = p.id AND t.locale = v.locale AND p.slug = v.slug;

-- ---------------------------------------------------------------------------
-- 3. The packs move. Everything under a SKU stays where it is.
-- ---------------------------------------------------------------------------

UPDATE skus s SET product_id = np.id, updated_at = now()
FROM products np
WHERE np.slug = 'mlbb-passes'
  AND s.sku_code IN ('mlbb-weekly-elite-pack', 'mlbb-weekly', 'mlbb-monthly-elite-pack', 'mlbb-twilight')
  AND s.product_id <> np.id;

UPDATE skus s SET product_id = np.id, updated_at = now()
FROM products np
WHERE np.slug = 'mlbb-passes-ru'
  AND s.sku_code IN ('mlbb_ru-limited-time-value-pack', 'mlbb_ru-weekly')
  AND s.product_id <> np.id;

-- ---------------------------------------------------------------------------
-- 4. Close the gaps the move left: 0..n-1 within each of the four products,
--    keeping the existing relative order (which is by price).
-- ---------------------------------------------------------------------------

UPDATE skus s SET sort_order = r.rn
FROM (
    SELECT s2.id, row_number() OVER (PARTITION BY s2.product_id ORDER BY s2.sort_order, s2.sku_code) - 1 AS rn
    FROM skus s2 JOIN products p ON p.id = s2.product_id
    WHERE p.slug IN ('mlbb-diamonds', 'mlbb-passes', 'mlbb-diamonds-ru', 'mlbb-passes-ru')
) r
WHERE r.id = s.id AND s.sort_order <> r.rn;

COMMIT;
