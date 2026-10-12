-- Bigo Live brand page: search titles, descriptions and a «what is it» FAQ.
--
-- Search Console, 3 months to 2026-10-11: the page gets ~100 impressions at
-- position ~4.7, and every Bigo query that reached us was written in Cyrillic
-- — «биго пополнение», «пополнить биго», «биго лайф пополнить» — plus Uzbek
-- «bigo live nima». The page said «Bigo» only in Latin and its title carried
-- neither «алмазы» nor «купить», so those queries matched nothing on it.
--
-- Titles stay under ~62 characters (the page adds « | yupay»); descriptions
-- under ~170. Idempotent: the FAQ row is replaced by sort_order.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 < scripts/seed/2026-10-12_bigo_seo.sql

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('ru',
   'Пополнить Bigo Live (Биго Лайв) — алмазы за сумы в Узбекистане',
   'Пополнение Биго Лайв: алмазы Bigo Live по Bigo ID, без пароля. Оплата в сумах через Click, Payme или Uzum, зачисление автоматическое.'),
  ('en',
   'Bigo Live diamonds — top up Bigo Live in Uzbekistan',
   'Buy Bigo Live diamonds by Bigo ID, no password. Pay in soʻm with Click, Payme or Uzum; diamonds are credited automatically.'),
  ('uz',
   'Bigo Live olmoslari — soʻmda toʻldirish, Oʻzbekiston',
   'Bigo Live olmoslarini Bigo ID orqali sotib oling, parolsiz. Click, Payme yoki Uzum orqali soʻmda toʻlov, olmoslar avtomatik tushadi.')
) AS v(locale, seo_title, seo_description)
WHERE b.slug = 'bigo-live' AND bt.brand_id = b.id AND bt.locale = v.locale;

-- The Russian body names the app the way people type it.
UPDATE brand_translations SET
  description = replace(
    description,
    'Bigo Live — приложение для прямых эфиров.',
    'Bigo Live (Биго Лайв) — приложение для прямых эфиров.')
WHERE locale = 'ru'
  AND brand_id = (SELECT id FROM brands WHERE slug = 'bigo-live')
  AND description NOT LIKE '%Биго Лайв%';

-- 5. What the app is — answers «bigo live nima» and «что такое биго».
DELETE FROM brand_faqs
 WHERE sort_order = 5 AND brand_id = (SELECT id FROM brands WHERE slug = 'bigo-live');

WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), id, 5, true FROM brands WHERE slug = 'bigo-live'
    RETURNING id
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM nf, (VALUES
    ('ru', $q$Что такое Bigo Live (Биго)?$q$,
        $a$Bigo Live — приложение для прямых эфиров: стримеры ведут трансляции, зрители общаются в чате и дарят подарки. Подарки покупают за алмазы — их можно пополнить здесь по Bigo ID.$a$),
    ('en', $q$What is Bigo Live?$q$,
        $a$Bigo Live is a live-streaming app: streamers broadcast, viewers chat and send gifts. Gifts are bought with diamonds, which you can top up here by Bigo ID.$a$),
    ('uz', $q$Bigo Live nima?$q$,
        $a$Bigo Live — jonli efirlar ilovasi: strimerlar efir oʻtkazadi, tomoshabinlar chatda yozishadi va sovgʻa qilishadi. Sovgʻalar olmosga sotib olinadi — ularni bu yerda Bigo ID orqali toʻldirish mumkin.$a$)
) AS t(locale, question, answer);

COMMIT;
