-- Platform gift cards (PlayStation, Xbox, Nintendo, App Store, Google Play,
-- Steam Wallet): an image on every country SKU and product (owner, 2026-11-24,
-- style A — a card in the platform's colour with the currency code; drawn and
-- uploaded to the CDN the same day). A product takes the image most of its SKUs
-- carry. Only rows without an image are touched. Idempotent.
BEGIN;

CREATE TEMP TABLE card(main text, code text, url text, PRIMARY KEY (main, code)) ON COMMIT DROP;
INSERT INTO card VALUES
  ('app-store', 'AED', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c41e-7e43-8fa5-595348af0cd5.png'),
  ('app-store', 'AUD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c516-7952-9037-85332e8efd54.png'),
  ('app-store', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c5c8-7f01-9a14-0fd9042f7b7b.png'),
  ('app-store', 'CHF', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c690-7721-9507-04620108e040.png'),
  ('app-store', 'CNY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c77a-7bf2-a624-229fc4723319.png'),
  ('app-store', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c81b-7c33-8720-cb598b1273b9.png'),
  ('app-store', 'GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c8f7-7a42-a1d8-61d5aec1de62.png'),
  ('app-store', 'HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-c9be-75d3-9c75-07850e51c2a0.png'),
  ('app-store', 'IDR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ca92-70b1-b798-87ab474aa886.png'),
  ('app-store', 'INR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-cbd1-7dd2-9f14-5a5b987fd581.png'),
  ('app-store', 'JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-cc8c-7a51-bf29-b7d7157c799b.png'),
  ('app-store', 'MXN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-cd33-72c2-89dd-4f8da4f4d10e.png'),
  ('app-store', 'NOK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ce08-73d0-a788-546e640d01f6.png'),
  ('app-store', 'NZD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-cebb-7133-aaaa-2f4002330b45.png'),
  ('app-store', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-cf93-7543-a4e3-1c237b8916c1.png'),
  ('app-store', 'RUB', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d04a-76e1-b811-70a712fd9b14.png'),
  ('app-store', 'SAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d105-7700-bf94-a4841f365fb0.png'),
  ('app-store', 'SEK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d1cf-7791-bbce-a5d72e8b6926.png'),
  ('app-store', 'TRY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d280-7a73-9a46-e8f1abb5c161.png'),
  ('app-store', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d362-7533-a498-89287726b21a.png'),
  ('google-play', 'AED', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d462-73d3-a35f-3c180a1d25d6.png'),
  ('google-play', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d53a-7c71-9510-beaa4a93f701.png'),
  ('google-play', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d5ed-7a22-8d08-e2abd184c012.png'),
  ('google-play', 'GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d69d-76e2-8924-7c90755e9f02.png'),
  ('google-play', 'IDR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d74f-7a73-bf7d-39efe9cde92c.png'),
  ('google-play', 'INR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d81a-7460-bb5c-41aa51c2c9ee.png'),
  ('google-play', 'JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d8b8-7f81-90e1-4f3961f53abb.png'),
  ('google-play', 'KRW', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-d95c-7772-8f7e-fa0b5bd6e125.png'),
  ('google-play', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-da6b-7a31-9b9a-f02723a94035.png'),
  ('google-play', 'SAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-db30-7d42-a509-506efe5969af.png'),
  ('google-play', 'TRY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-dbed-7342-a4cf-422f30b38296.png'),
  ('google-play', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-dcaf-7ca2-be2c-1a1ee6d5c39f.png'),
  ('nintendo', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-dd6a-7262-a052-884791f10dd9.png'),
  ('nintendo', 'CAD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-de0e-7ce0-ad32-bbdf6e85cb76.png'),
  ('nintendo', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-decd-7a10-a5ac-6c8aa7d52931.png'),
  ('nintendo', 'GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-dfa8-7fa3-a0a4-202984cbb9d8.png'),
  ('nintendo', 'HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e085-71e2-84f6-47669da25d89.png'),
  ('nintendo', 'JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e119-7ba1-bedd-a375c64f630d.png'),
  ('nintendo', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e1ce-7a70-bb3c-0d3f7b97a56d.png'),
  ('nintendo', 'SEK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e30e-7550-8fd0-a231446982cc.png'),
  ('nintendo', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e3f0-7242-9a03-f0bdf16cc5eb.png'),
  ('playstation', 'AUD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e4ad-7a80-ae24-15b3c862d236.png'),
  ('playstation', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e55a-78f2-8a69-258d2a3dd623.png'),
  ('playstation', 'CAD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e606-7d52-b8ce-37fadb25c9e6.png'),
  ('playstation', 'CHF', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e6a1-7410-b36c-92253b7f213f.png'),
  ('playstation', 'CZK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e753-7893-90a9-9015061c519a.png'),
  ('playstation', 'DKK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e833-7330-9429-075c1477ce4d.png'),
  ('playstation', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e8cc-7363-81e5-8a2b3e929cc5.png'),
  ('playstation', 'GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-e970-7420-90e5-092ae75b72f3.png'),
  ('playstation', 'HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ea5b-7213-a23b-b019357c6269.png'),
  ('playstation', 'HUF', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-eb25-7893-a19f-57e7bdf77745.png'),
  ('playstation', 'IDR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ec2f-7640-a76f-566003b459a1.png'),
  ('playstation', 'INR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ecf7-7a92-a2a9-de490da6d0a7.png'),
  ('playstation', 'JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-eda8-76f2-aa94-f87ddd00ecf9.png'),
  ('playstation', 'MYR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ee69-7632-ac42-23f8986661f3.png'),
  ('playstation', 'NOK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ef42-7140-a293-82daf29002a5.png'),
  ('playstation', 'NZD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-efe6-7fa3-8d95-c4752da5492f.png'),
  ('playstation', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f09d-7f32-be48-6e421e8f67cb.png'),
  ('playstation', 'RON', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f18b-7682-a1c4-4d94dc9a5f95.png'),
  ('playstation', 'SGD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f265-7a32-84ca-4ca0c6d61ca7.png'),
  ('playstation', 'THB', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f342-73a2-b08c-01db70bbe3a9.png'),
  ('playstation', 'TRY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f3fd-7e02-b8c0-b049313ecea5.png'),
  ('playstation', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f4c3-7d70-a461-3db7a842b74f.png'),
  ('playstation', 'ZAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f573-7770-8c22-880c0415612e.png'),
  ('steam-wallet', 'AED', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f61d-7631-a10c-514204d26d31.png'),
  ('steam-wallet', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f6c6-7711-aeb4-d12a03524b9a.png'),
  ('steam-wallet', 'CLP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f78a-7f61-a7ae-a0d366131b30.png'),
  ('steam-wallet', 'CNY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f857-7500-a307-38facf3279ac.png'),
  ('steam-wallet', 'COP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-f92c-79f0-bbe6-adfabfef20e9.png'),
  ('steam-wallet', 'CRC', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fa2c-73c0-92be-67661a729835.png'),
  ('steam-wallet', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fb02-7781-a566-5ad80ecef3ff.png'),
  ('steam-wallet', 'HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fbc8-7e61-8828-b83a45200254.png'),
  ('steam-wallet', 'IDR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fc67-7fd1-b53b-e0a02b98d4ba.png'),
  ('steam-wallet', 'INR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fd2c-7c33-92a9-e60398d773ca.png'),
  ('steam-wallet', 'KRW', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fdd5-7631-b345-9caf98c6cd2c.png'),
  ('steam-wallet', 'KWD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-fea4-7d41-b096-afd519460089.png'),
  ('steam-wallet', 'MXN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e73-ff5c-7531-8db9-ba7143dae48c.png'),
  ('steam-wallet', 'MYR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0019-76b0-a194-1384da078893.png'),
  ('steam-wallet', 'PEN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-00b2-7df0-b64f-bb3606b41da3.png'),
  ('steam-wallet', 'PHP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0157-7212-9e85-f0454aa8267d.png'),
  ('steam-wallet', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0220-7bc1-b0b0-71eed2936c22.png'),
  ('steam-wallet', 'QAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-038f-7232-91d1-120b9674d505.png'),
  ('steam-wallet', 'SAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0427-7e42-9a11-0fa4ce4eb262.png'),
  ('steam-wallet', 'SGD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-04d6-7070-a3a4-16e8446dbfdc.png'),
  ('steam-wallet', 'THB', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-05b3-7b92-b118-b28affb1473a.png'),
  ('steam-wallet', 'TWD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0664-7a32-b12b-0bf1784971c2.png'),
  ('steam-wallet', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0712-79d0-b25b-c0bb512d55f7.png'),
  ('steam-wallet', 'UYU', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-07e6-7cd3-b816-adac1d6272ca.png'),
  ('steam-wallet', 'VND', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-08bc-7d83-b898-80eb6ae3cbf5.png'),
  ('steam-wallet', 'ZAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0973-7e50-894a-33dbb9aed369.png'),
  ('xbox', 'AED', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0a57-71d2-b09e-bd0282adb5f4.png'),
  ('xbox', 'AUD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0b58-7f61-998a-c585845d9310.png'),
  ('xbox', 'BRL', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0c14-78e0-b4d8-04f609795220.png'),
  ('xbox', 'CAD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0cd3-7ef2-8230-09dad84feaf1.png'),
  ('xbox', 'COP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0d63-7f02-bf16-7bb8008c5794.png'),
  ('xbox', 'CZK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0e2d-7063-a5c0-30a04396b3ca.png'),
  ('xbox', 'DKK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0ed0-7cf1-bb04-4941ecf41f39.png'),
  ('xbox', 'EUR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-0f83-7d01-b3c2-462b2d036c77.png'),
  ('xbox', 'GBP', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-1026-73a3-8db2-bd176af9cda5.png'),
  ('xbox', 'HKD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-10bf-79b2-b856-203116082ace.png'),
  ('xbox', 'HUF', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-119e-7043-931f-d283630f9b98.png'),
  ('xbox', 'JPY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-125e-71b2-8d4c-c91ca82b6f54.png'),
  ('xbox', 'MXN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-1313-7172-aee1-b5e69e255dcb.png'),
  ('xbox', 'NOK', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-13a4-7cd1-931d-3bd5d2a88885.png'),
  ('xbox', 'PLN', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-145e-7d21-8036-1ccb9fc698e6.png'),
  ('xbox', 'SAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-151c-73b2-9d28-c2164c2fdd2e.png'),
  ('xbox', 'TRY', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-15dc-78d2-a911-bfd3acdf7882.png'),
  ('xbox', 'USD', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-16a1-7072-bb66-f71290cd3346.png'),
  ('xbox', 'ZAR', 'https://cdn.yupay.uz/product_image/2026/11/01a20e74-174f-70c3-b9bb-9d32785d1447.png');

UPDATE skus s SET image_url = card.url
FROM products p, brands b, brands m, card
WHERE p.id = s.product_id AND b.id = p.brand_id AND m.id = b.region_parent_id
  AND card.main = m.slug
  AND card.code = regexp_replace(s.denomination, '^[0-9.,]+ *', '')
  AND s.image_url IS NULL;

UPDATE products p SET image_url = x.url
FROM (
  SELECT s.product_id, mode() WITHIN GROUP (ORDER BY s.image_url) AS url
  FROM skus s JOIN products p2 ON p2.id = s.product_id
  JOIN brands b ON b.id = p2.brand_id JOIN brands m ON m.id = b.region_parent_id
  WHERE m.slug IN (SELECT DISTINCT main FROM card) AND s.image_url IS NOT NULL
  GROUP BY s.product_id
) x
WHERE p.id = x.product_id AND p.image_url IS NULL;

SELECT m.slug,
       count(DISTINCT s.id) FILTER (WHERE s.image_url IS NOT NULL) AS skus_with_image,
       count(DISTINCT s.id) AS skus,
       count(DISTINCT p.id) FILTER (WHERE p.image_url IS NOT NULL) AS products_with_image,
       count(DISTINCT p.id) AS products
FROM skus s JOIN products p ON p.id = s.product_id
JOIN brands b ON b.id = p.brand_id JOIN brands m ON m.id = b.region_parent_id
WHERE m.slug IN (SELECT DISTINCT main FROM card)
GROUP BY m.slug ORDER BY m.slug;

COMMIT;
