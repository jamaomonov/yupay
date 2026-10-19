-- Likee brand page: search titles, descriptions and a «what is it» FAQ.
--
-- Search Console, 3 months to 2026-10-19: /uz/store/likee takes 18 clicks
-- from 28 impressions at position 2, but /store/likee (ru) only 5 from 55
-- at ~4.2, and /en/store/likee none. All three had an empty seo_title, so
-- the page fell back to the generic template — no «алмазы», no «купить»,
-- and no «Лайки», the way Russian speakers type the app's name. Same fix as
-- Bigo Live (2026-10-12_bigo_seo.sql).
--
-- Titles stay under ~62 characters (the page adds « | yupay»); descriptions
-- under ~170. Idempotent: the FAQ row is replaced by sort_order.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 < scripts/seed/2026-10-19_likee_seo.sql

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('ru',
   'Алмазы Likee (Лайки) — пополнить за сумы в Узбекистане',
   'Пополнение Лайки: алмазы Likee от 100 до 20 000 по Likee ID, без пароля. Оплата в сумах через Click, Payme или Uzum, зачисление автоматическое.'),
  ('en',
   'Likee diamonds — top up Likee in Uzbekistan',
   'Buy Likee diamonds, 100 to 20,000, by Likee ID, no password. Pay in soʻm with Click, Payme or Uzum; diamonds are credited automatically.'),
  ('uz',
   'Likee olmoslari — soʻmda toʻldirish, Oʻzbekiston',
   'Likee olmoslarini Likee ID orqali sotib oling: 100 dan 20 000 gacha, parolsiz. Click, Payme yoki Uzum orqali soʻmda toʻlov, olmoslar avtomatik tushadi.')
) AS v(locale, seo_title, seo_description)
WHERE b.slug = 'likee' AND bt.brand_id = b.id AND bt.locale = v.locale;

-- The Russian body names the app the way people type it.
UPDATE brand_translations SET
  description = replace(
    description,
    'Likee — приложение коротких видео и прямых эфиров.',
    'Likee (Лайки) — приложение коротких видео и прямых эфиров.')
WHERE locale = 'ru'
  AND brand_id = (SELECT id FROM brands WHERE slug = 'likee')
  AND description NOT LIKE '%Лайки%';

-- 5. What the app is — answers «likee nima» and «что такое лайки».
DELETE FROM brand_faqs
 WHERE sort_order = 5 AND brand_id = (SELECT id FROM brands WHERE slug = 'likee');

WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), id, 5, true FROM brands WHERE slug = 'likee'
    RETURNING id
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM nf, (VALUES
    ('ru', $q$Что такое Likee (Лайки)?$q$,
        $a$Likee — приложение коротких видео и прямых эфиров. Зрители дарят авторам подарки, а подарки покупают за алмазы — их можно пополнить здесь по Likee ID.$a$),
    ('en', $q$What is Likee?$q$,
        $a$Likee is a short-video and live-streaming app. Viewers send creators gifts, and gifts are bought with diamonds, which you can top up here by Likee ID.$a$),
    ('uz', $q$Likee nima?$q$,
        $a$Likee — qisqa videolar va jonli efirlar ilovasi. Tomoshabinlar mualliflarga sovgʻa qiladi, sovgʻalar esa olmosga sotib olinadi — ularni bu yerda Likee ID orqali toʻldirish mumkin.$a$)
) AS t(locale, question, answer);

COMMIT;
