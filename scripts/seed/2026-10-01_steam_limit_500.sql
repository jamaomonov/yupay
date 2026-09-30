-- Steam top-up limit: the copy said $1–$300 per order, the `steam-wallet-usd` SKU
-- takes up to $500 (owner confirmed $500, 2026-10-01). Rewrites every place that
-- quotes the old ceiling: the Steam brand's copy and FAQ, and the Steam blog posts
-- (`steam`, `steam-koshelek` and their en/uz twins) with their FAQs.
--
-- Two exact phrasings are replaced and nothing else: «$300» and «300 долларов».
-- Scoped to Steam rows so «300 UC» and the like elsewhere are untouched.
-- Idempotent: a second run finds nothing to replace.

BEGIN;

UPDATE brand_translations bt SET
  short_description = replace(replace(short_description, '$300', '$500'), '300 долларов', '500 долларов'),
  description = replace(replace(description, '$300', '$500'), '300 долларов', '500 долларов'),
  instructions = replace(replace(instructions, '$300', '$500'), '300 долларов', '500 долларов')
FROM brands b
WHERE b.id = bt.brand_id AND b.slug = 'steam';

UPDATE brand_faq_translations ft SET
  answer = replace(replace(ft.answer, '$300', '$500'), '300 долларов', '500 долларов')
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE f.id = ft.brand_faq_id AND b.slug = 'steam';

WITH steam_posts AS (
  SELECT DISTINCT post_id FROM blog_post_translations
  WHERE slug IN ('steam', 'steam-koshelek', 'steam-wallet-top-up-and-spend', 'steam-hamyoni')
)
UPDATE blog_post_translations t SET
  body_html = replace(replace(t.body_html, '$300', '$500'), '300 долларов', '500 долларов'),
  excerpt = replace(replace(t.excerpt, '$300', '$500'), '300 долларов', '500 долларов'),
  seo_description = replace(replace(t.seo_description, '$300', '$500'), '300 долларов', '500 долларов')
WHERE t.post_id IN (SELECT post_id FROM steam_posts);

WITH steam_posts AS (
  SELECT DISTINCT post_id FROM blog_post_translations
  WHERE slug IN ('steam', 'steam-koshelek', 'steam-wallet-top-up-and-spend', 'steam-hamyoni')
)
UPDATE blog_post_faqs f SET
  answer = replace(replace(f.answer, '$300', '$500'), '300 долларов', '500 долларов'),
  question = replace(replace(f.question, '$300', '$500'), '300 долларов', '500 долларов')
WHERE f.post_id IN (SELECT post_id FROM steam_posts);

COMMIT;
