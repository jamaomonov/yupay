-- Currency coins on the SKU tiles and products of the six new storefront brands
-- (owner, 2026-11-25): VP, RP, V-Bucks, CP, FC Points, G-Coin — a coin in the
-- game's colours with the currency's short name, no publisher logos. Only rows
-- without an image are touched. Idempotent.
BEGIN;

CREATE TEMP TABLE coin(pattern text, url text) ON COMMIT DROP;
INSERT INTO coin VALUES
  ('valorant-vp-%', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-cd44-7e02-acba-404d105124c3.png'),
  ('league-of-legends-rp-%', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-cbbb-78a3-bec3-4be4d57acfc3.png'),
  ('fortnite-%', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-cb05-79c1-a9c2-10571ef65737.png'),
  ('call-of-duty-mobile-activision-%', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-c932-7080-ac54-269d0cd9cb84.png'),
  ('ea-sports-fc-26%', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-ca4f-7531-bc7c-e91787cac705.png'),
  ('pubg-battlegrounds', 'https://cdn.yupay.uz/product_image/2026/11/01a21044-cc64-7450-a994-1672338c50f3.png');

UPDATE skus s SET image_url = c.url
  FROM products p, brands b, coin c
 WHERE p.id = s.product_id AND b.id = p.brand_id AND b.slug LIKE c.pattern
   AND s.image_url IS NULL;

UPDATE products p SET image_url = c.url
  FROM brands b, coin c
 WHERE b.id = p.brand_id AND b.slug LIKE c.pattern AND p.image_url IS NULL;

SELECT c.pattern, count(s.id) FILTER (WHERE s.image_url = c.url) AS with_coin, count(s.id) AS skus
  FROM coin c JOIN brands b ON b.slug LIKE c.pattern
  JOIN products p ON p.brand_id = b.id JOIN skus s ON s.product_id = p.id
 GROUP BY 1 ORDER BY 1;

COMMIT;
