-- Roblox regions: an image on every SKU tile (owner, 2026-11-24).
-- Robux packs get the global product's Robux mark; currency cards get a gold
-- gift-card mark with the currency code (drawn 2026-11-24, uploaded to the CDN).
-- Only SKUs without an image of their own are touched. Idempotent.
BEGIN;

CREATE TEMP TABLE cur(code text PRIMARY KEY, url text) ON COMMIT DROP;
INSERT INTO cur VALUES
  ('AED', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1388-7123-853d-6aa7c2aac047.png'),
  ('AUD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-14f7-76a3-a2e5-2ec2c608b070.png'),
  ('BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1611-70a2-93c8-13b490f6086c.png'),
  ('CAD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1853-7c60-9135-3ee74536809e.png'),
  ('CHF', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-19a0-7eb2-8707-091f7f6b3221.png'),
  ('DKK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1a76-7112-824e-38b4b4036408.png'),
  ('EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1b5e-7103-9e21-692831ab0d18.png'),
  ('GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1c8d-77a1-9153-6ef076176ad7.png'),
  ('HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1d7c-7f20-92d0-4629a18af2c0.png'),
  ('IDR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1e3b-7dc2-ab10-291f8de7ba81.png'),
  ('JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1efe-7713-b3f9-6aa7ea43ddbb.png'),
  ('MXN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-1fcf-76a0-a9b5-529a6b6ba0f6.png'),
  ('MYR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-2094-7810-9659-b64bc346a3ca.png'),
  ('NOK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-2185-7db3-b8d9-d46f2854e516.png'),
  ('NZD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-2265-7781-9a9a-6c18205b095e.png'),
  ('PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-23a3-7d52-b9cd-f5a313970ebf.png'),
  ('SAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-24ac-75f0-84c7-9d54f7223ff0.png'),
  ('SEK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-2597-7823-ac67-d64b0be5f8b5.png'),
  ('SGD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-272e-7bc2-ad41-cfe5a622692c.png'),
  ('THB', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-27fe-7462-973a-98490892c984.png'),
  ('USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-28ef-76f2-90f3-490659afbeaa.png'),
  ('ZAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e63-29d7-7172-8679-c4127664b72e.png');

WITH fam AS (
  SELECT p.id FROM products p JOIN brands b ON b.id = p.brand_id
  WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'roblox')
)
UPDATE skus s SET image_url = (SELECT image_url FROM products WHERE slug = 'roblox-robux-global')
FROM fam WHERE s.product_id = fam.id AND s.image_url IS NULL AND s.denomination LIKE '% Robux';

WITH fam AS (
  SELECT p.id FROM products p JOIN brands b ON b.id = p.brand_id
  WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'roblox')
)
UPDATE skus s SET image_url = cur.url
FROM fam, cur WHERE s.product_id = fam.id AND s.image_url IS NULL
  AND split_part(s.denomination, ' ', 2) = cur.code;

SELECT count(*) FILTER (WHERE s.image_url IS NOT NULL) AS with_image, count(*) AS total
FROM skus s JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'roblox');

COMMIT;
