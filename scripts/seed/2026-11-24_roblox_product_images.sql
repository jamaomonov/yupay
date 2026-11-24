-- Roblox regions: each country product takes the image most of its SKUs carry
-- (owner, 2026-11-24): Robux mark for Russia, the currency card elsewhere
-- (USD for the US, where currency cards outnumber Robux packs). Run after
-- 2026-11-24_roblox_sku_images.sql. Only products without an image. Idempotent.
BEGIN;

UPDATE products p SET image_url = m.url
FROM (
  SELECT s.product_id, mode() WITHIN GROUP (ORDER BY s.image_url) AS url
  FROM skus s JOIN products p2 ON p2.id = s.product_id JOIN brands b ON b.id = p2.brand_id
  WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'roblox')
    AND s.image_url IS NOT NULL
  GROUP BY s.product_id
) m
WHERE p.id = m.product_id AND p.image_url IS NULL;

SELECT count(p.image_url) AS with_image, count(*) AS total
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'roblox');

COMMIT;
