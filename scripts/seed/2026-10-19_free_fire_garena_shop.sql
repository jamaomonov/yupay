-- Free Fire: the «is this official» FAQ names Garena Shop.
--
-- Search Console, 3 months to 2026-10-19: «garena shop uz» (85 impressions,
-- position 5.7) and «garena shop uzbekistan» (78, position 4.7) reach the
-- Free Fire page, which never said «Garena Shop». FAQ 6 already answers «is
-- this official»; it now asks it the way those people search, and says what
-- they can expect instead: the same account, credited by player ID.
--
-- Idempotent: rewrites FAQ 6's three translations in place.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 < scripts/seed/2026-10-19_free_fire_garena_shop.sql

BEGIN;

UPDATE brand_faq_translations ft SET
  question = v.question,
  answer = v.answer
FROM brand_faqs f, brands b, (VALUES
  ('ru', $q$Это официальный Garena Shop или сайт Free Fire?$q$,
      $a$Нет. YuPay — независимый сервис пополнения и не связан с Garena, издателем Free Fire. Алмазы приходят на тот же аккаунт по ID игрока, что и при покупке в Garena Shop, а цена в сумах видна до оплаты.$a$),
  ('en', $q$Is this the official Garena Shop or Free Fire website?$q$,
      $a$No. YuPay is an independent top-up service and is not affiliated with Garena, the publisher of Free Fire. Diamonds reach the same account by player ID as a Garena Shop purchase would, and the price in soʻm is shown before you pay.$a$),
  ('uz', $q$Bu rasmiy Garena Shop yoki Free Fire saytimi?$q$,
      $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Free Fire noshiri Garena bilan bogʻliq emas. Olmoslar Garena Shop’dagi kabi oʻsha akkauntga oʻyinchi ID si orqali tushadi, soʻmdagi narx esa toʻlovdan oldin koʻrinadi.$a$)
) AS v(locale, question, answer)
WHERE b.slug = 'free-fire'
  AND f.brand_id = b.id
  AND f.sort_order = 6
  AND ft.brand_faq_id = f.id
  AND ft.locale = v.locale;

COMMIT;
