-- Standoff 2 search titles + «how much» FAQs for Standoff 2 and Roblox.
--
-- Search Console, 3 months to 2026-10-11: /store/standoff-2 had 834
-- impressions at position 5.6 under the bare template title «Standoff 2 —
-- купить в Узбекистане», while the queries reaching it were «купить голду»
-- and «standoff 2 gold sotib olish». «сколько стоит 1000 робуксов в сумах»
-- had 42 impressions at position 4.7 and no clicks: neither brand answered
-- a price question. PUBG's «Сколько стоит 660 UC в сумах?» is the pattern.
--
-- Prices are a guide taken from the storefront on 2026-10-12 and say so;
-- the answer points at the price shown before payment. Idempotent.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 < scripts/seed/2026-10-12_standoff_roblox_seo.sql

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('ru',
   'Голда Standoff 2 (Gold) — купить за сумы в Узбекистане',
   'Промокод на голду Standoff 2: от 100 до 3000 Gold, код приходит на почту. Оплата в сумах через Click, Payme или Uzum, без пароля от аккаунта.'),
  ('en',
   'Standoff 2 Gold — buy a promo code in Uzbekistan for soʻm',
   'Standoff 2 Gold promo codes from 100 to 3000 Gold, delivered by email. Pay in soʻm with Click, Payme or Uzum. No account password.'),
  ('uz',
   'Standoff 2 Gold sotib olish — soʻmda, Oʻzbekiston',
   'Standoff 2 Gold promokodi: 100 dan 3000 Gold gacha, kod pochtaga keladi. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(locale, seo_title, seo_description)
WHERE b.slug = 'standoff-2' AND bt.brand_id = b.id AND bt.locale = v.locale;

DELETE FROM brand_faqs
 WHERE (brand_id, sort_order) IN (
   SELECT id, 7 FROM brands WHERE slug = 'roblox'
   UNION ALL
   SELECT id, 8 FROM brands WHERE slug = 'standoff-2');

WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.sort_order, true
    FROM brands b JOIN (VALUES ('roblox', 7), ('standoff-2', 8)) AS v(slug, sort_order)
      ON v.slug = b.slug
    RETURNING id, brand_id
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM nf
JOIN brands b ON b.id = nf.brand_id
JOIN (VALUES
    ('roblox', 'ru', $q$Сколько стоит 1000 Robux в сумах?$q$,
        $a$Актуальная цена показывается до оплаты и зависит от курса. Ориентир: 1000 Robux ≈ 151 000 сум, 800 Robux ≈ 122 000 сум, 2000 Robux ≈ 298 000 сум. Всего 15 номиналов — от 50 до 24 000 Robux. Комиссии сверху нет, итог виден до подтверждения.$a$),
    ('roblox', 'en', $q$How much does 1,000 Robux cost in sum?$q$,
        $a$The current price is shown before payment and depends on the exchange rate. As a guide: 1,000 Robux ≈ 151,000 sum, 800 Robux ≈ 122,000 sum, 2,000 Robux ≈ 298,000 sum. There are 15 denominations, from 50 to 24,000 Robux. No extra commission; the total is shown before you confirm.$a$),
    ('roblox', 'uz', $q$1000 Robux soʻmda qancha turadi?$q$,
        $a$Joriy narx toʻlovdan oldin koʻrsatiladi va kursga bogʻliq. Taxminan: 1000 Robux ≈ 151 000 soʻm, 800 Robux ≈ 122 000 soʻm, 2000 Robux ≈ 298 000 soʻm. Jami 15 ta nominal — 50 dan 24 000 Robux gacha. Ustiga komissiya yoʻq, yakuniy summa tasdiqlashdan oldin koʻrinadi.$a$),
    ('standoff-2', 'ru', $q$Сколько стоит голда в Standoff 2?$q$,
        $a$Актуальная цена показывается до оплаты и зависит от курса. Ориентир: 100 Gold ≈ 22 000 сум, 500 Gold ≈ 96 000 сум, 1000 Gold ≈ 169 000 сум, 3000 Gold ≈ 359 000 сум. Комиссии сверху нет, итог виден до подтверждения.$a$),
    ('standoff-2', 'en', $q$How much does Standoff 2 Gold cost?$q$,
        $a$The current price is shown before payment and depends on the exchange rate. As a guide: 100 Gold ≈ 22,000 sum, 500 Gold ≈ 96,000 sum, 1,000 Gold ≈ 169,000 sum, 3,000 Gold ≈ 359,000 sum. No extra commission; the total is shown before you confirm.$a$),
    ('standoff-2', 'uz', $q$Standoff 2 Gold qancha turadi?$q$,
        $a$Joriy narx toʻlovdan oldin koʻrsatiladi va kursga bogʻliq. Taxminan: 100 Gold ≈ 22 000 soʻm, 500 Gold ≈ 96 000 soʻm, 1000 Gold ≈ 169 000 soʻm, 3000 Gold ≈ 359 000 soʻm. Ustiga komissiya yoʻq, yakuniy summa tasdiqlashdan oldin koʻrinadi.$a$)
) AS t(slug, locale, question, answer) ON t.slug = b.slug;

COMMIT;
