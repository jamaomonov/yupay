-- Xbox Game Pass on the storefront (owner, 2026-11-25): one card, the countries on
-- its region switcher (ADR-0099), the same shape as the platform cards of
-- 2026-11-24_platform_gift_card_regions.sql, which left Game Pass out.
--
-- - `xbox-game-pass` is a main brand that sells nothing itself and opens on the US.
-- - Nine country brands become its regions: au br eu hk in jp mx sg us.
--   MENA stays B2B-only — its packs are named only "Xbox Game Pass", with no tier.
-- - Each SKU's name becomes "<tier> · <N> месяц(а/ев)", with a tier card image.
-- - Two duplicates of the US "Ultimate · 1 месяц" are switched off, keeping
--   the G2B one. None of the three sold in 90 days.
-- - The US Non-Stackable Ultimate pack gets a notice.
--
-- Rollback: UPDATE brands SET visible_retail = false WHERE slug = 'xbox-game-pass';
-- (the regions are reachable only through it).
--
-- Idempotent. Apply with operator psql:
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-11-25_xbox_game_pass_storefront.sql

BEGIN;

CREATE TEMP TABLE country (code text, ru text, en text, uz text) ON COMMIT DROP;
INSERT INTO country VALUES
    ('au', 'Австралия', 'Australia', 'Avstraliya'),
    ('br', 'Бразилия', 'Brazil', 'Braziliya'),
    ('eu', 'Европа', 'Europe', 'Yevropa'),
    ('hk', 'Гонконг', 'Hong Kong', 'Gonkong'),
    ('in', 'Индия', 'India', 'Hindiston'),
    ('jp', 'Япония', 'Japan', 'Yaponiya'),
    ('mx', 'Мексика', 'Mexico', 'Meksika'),
    ('sg', 'Сингапур', 'Singapore', 'Singapur'),
    ('us', 'США', 'USA', 'AQSH');

-- 1. The main brand: category and logo of the US card.
INSERT INTO brands (id, slug, category_id, logo_url, sort_order, active,
                    visible_b2b, visible_retail, region_code)
SELECT gen_random_uuid(), 'xbox-game-pass', us.category_id, us.logo_url, 30, true, false, true, 'us'
  FROM brands us WHERE us.slug = 'xbox-game-pass-us'
ON CONFLICT (slug) DO UPDATE
   SET region_code = 'us', visible_retail = true, active = true, updated_at = now();

INSERT INTO brand_translations (brand_id, locale, name)
SELECT b.id, l.locale, 'Xbox Game Pass'
  FROM brands b CROSS JOIN (VALUES ('ru'), ('en'), ('uz')) AS l(locale)
 WHERE b.slug = 'xbox-game-pass'
ON CONFLICT (brand_id, locale) DO UPDATE SET name = EXCLUDED.name;

-- 2. Countries become its regions.
UPDATE brands c
   SET region_parent_id = m.id, region_code = k.code, visible_retail = true, updated_at = now()
  FROM brands m, country k
 WHERE m.slug = 'xbox-game-pass' AND c.slug = 'xbox-game-pass-' || k.code AND c.active;

UPDATE brand_translations t
   SET name = 'Xbox Game Pass · ' || CASE t.locale WHEN 'ru' THEN k.ru WHEN 'en' THEN k.en ELSE k.uz END
  FROM brands c JOIN country k ON c.slug = 'xbox-game-pass-' || k.code
 WHERE t.brand_id = c.id;

-- 3. Duplicates of US Ultimate 1 month: keep the G2B SKU.
UPDATE skus SET active = false, updated_at = now()
 WHERE sku_code IN ('xbox-game-pass-us-1-month-xbox-game-pass-ultimate',
                    'xbox-game-pass-us-ultimate-1-month');

-- 4. Names, order and images from the tier and the term.
CREATE TEMP TABLE gp ON COMMIT DROP AS
SELECT s.id,
       CASE WHEN lower(s.denomination) LIKE '%pc game pass%' THEN 'pc'
            WHEN lower(s.denomination) LIKE '%ultimate%' THEN 'ultimate'
            WHEN lower(s.denomination) LIKE '%premium%' THEN 'premium'
            WHEN lower(s.denomination) LIKE '%essential%' THEN 'essential'
            WHEN lower(s.denomination) LIKE '%core%' THEN 'core' END AS tier,
       substring(s.denomination from '([0-9]+)\s*[Mm]onth')::int AS months,
       lower(s.denomination) LIKE '%non-stack%' AS nonstack
  FROM skus s JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
 WHERE b.region_parent_id = (SELECT id FROM brands WHERE slug = 'xbox-game-pass')
   AND s.active;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM gp WHERE tier IS NULL OR months IS NULL) THEN
    RAISE EXCEPTION 'unparsed Game Pass SKU: %', (SELECT string_agg(id::text, ',') FROM gp WHERE tier IS NULL OR months IS NULL);
  END IF;
END $$;

UPDATE skus s
   SET denomination =
         CASE g.tier WHEN 'pc' THEN 'PC Game Pass' WHEN 'ultimate' THEN 'Ultimate'
                     WHEN 'premium' THEN 'Premium' WHEN 'essential' THEN 'Essential' ELSE 'Core' END
         || ' · ' || g.months || ' '
         || CASE WHEN g.months = 1 THEN 'месяц' WHEN g.months IN (2, 3, 4) THEN 'месяца' ELSE 'месяцев' END
         || CASE WHEN g.nonstack THEN ' (новая подписка)' ELSE '' END,
       sort_order = CASE g.tier WHEN 'essential' THEN 100 WHEN 'core' THEN 200 WHEN 'premium' THEN 300
                                WHEN 'ultimate' THEN 400 ELSE 500 END + g.months + CASE WHEN g.nonstack THEN 0 ELSE 50 END,
       image_url = CASE g.tier
         WHEN 'ultimate' THEN 'https://cdn.yupay.uz/product_image/2026/11/01a21092-c093-7353-9b3a-e7399d8e45a8.png'
         WHEN 'premium' THEN 'https://cdn.yupay.uz/product_image/2026/11/01a21092-bfda-7e30-8c39-062542214724.png'
         WHEN 'essential' THEN 'https://cdn.yupay.uz/product_image/2026/11/01a21092-beca-7a13-9828-7d0bf0208e6a.png'
         WHEN 'core' THEN 'https://cdn.yupay.uz/product_image/2026/11/01a21092-be0d-7a52-89a5-3bfe597930f4.png'
         ELSE 'https://cdn.yupay.uz/product_image/2026/11/01a21092-bf51-77b0-b424-0fbd4cae6109.png' END,
       notice = CASE WHEN g.nonstack THEN jsonb_build_object(
         'badge', jsonb_build_object('ru', 'Только новая подписка', 'en', 'New subscription only',
                                     'uz', 'Faqat yangi obuna'),
         'text', jsonb_build_object(
           'ru', 'Код подходит только для аккаунта без действующей подписки Game Pass. Продлить им текущую подписку нельзя.',
           'en', 'The code works only on an account with no active Game Pass subscription. It cannot extend a current one.',
           'uz', 'Kod faqat faol Game Pass obunasi yoʻq akkauntga mos keladi. U bilan joriy obunani uzaytirib boʻlmaydi.'))
         ELSE s.notice END,
       updated_at = now()
  FROM gp g WHERE s.id = g.id;

-- Products take their SKUs' image.
UPDATE products p
   SET image_url = (SELECT s.image_url FROM skus s WHERE s.product_id = p.id AND s.active
                     ORDER BY s.sort_order LIMIT 1)
  FROM brands b
 WHERE p.brand_id = b.id
   AND b.region_parent_id = (SELECT id FROM brands WHERE slug = 'xbox-game-pass')
   AND p.image_url IS NULL;

-- 5. Page copy on the main brand.
UPDATE brand_translations t SET
    seo_title = v.seo_title, seo_description = v.seo_description,
    short_description = v.short, description = v.descr, instructions = v.instr,
    highlights = v.hl::json
  FROM brands b, (VALUES
    ('ru',
     'Xbox Game Pass — купить подписку в Узбекистане за сумы',
     'Коды Xbox Game Pass Ultimate, Premium и Essential на 1–12 месяцев для США, Европы, Индии, Бразилии и других стран. Оплата в сумах через Click, Payme или Uzum.',
     'Коды подписки Xbox Game Pass: Ultimate, Premium и Essential, страна на выбор.',
     E'Game Pass — подписка Microsoft на каталог игр для Xbox и ПК. Ultimate включает всё: игры в день релиза, ПК, облачный гейминг и онлайн. Premium и Essential — более лёгкие тарифы.\n\nКод привязан к стране: он активируется на аккаунте Microsoft того же региона. Выберите страну своего аккаунта на переключателе.\n\nОплата в сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты, и списывается ровно он.',
     E'Как активировать код:\n\n1. Войдите в аккаунт Microsoft, на котором будет подписка.\n2. Откройте redeem.microsoft.com или на Xbox: Магазин → Использовать код.\n3. Введите код из 25 символов и подтвердите.\n\nКод появится на странице заказа и придёт на почту после оплаты.',
     '["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]'),
    ('en',
     'Xbox Game Pass — buy a subscription in Uzbekistan in UZS',
     'Xbox Game Pass Ultimate, Premium and Essential codes for 1–12 months: USA, Europe, India, Brazil and more. Pay in soʻm via Click, Payme or Uzum.',
     'Xbox Game Pass subscription codes: Ultimate, Premium and Essential, pick your country.',
     E'Game Pass is Microsoft''s game library subscription for Xbox and PC. Ultimate has everything: day-one games, PC, cloud gaming and online play. Premium and Essential are lighter tiers.\n\nA code is tied to a country: it redeems on a Microsoft account of the same region. Pick your account''s country on the switcher.\n\nPay in soʻm via Click, Payme or Uzum. The total in soʻm is shown before you pay, and exactly that is charged.',
     E'How to redeem the code:\n\n1. Sign in to the Microsoft account that will get the subscription.\n2. Open redeem.microsoft.com, or on Xbox: Store → Redeem.\n3. Enter the 25-character code and confirm.\n\nThe code appears on the order page and is emailed to you after payment.',
     '["Pay in UZS", "Code by email", "Pick your country", "No password"]'),
    ('uz',
     'Xbox Game Pass — Oʻzbekistonda soʻmga obuna sotib olish',
     'Xbox Game Pass Ultimate, Premium va Essential kodlari 1–12 oyga: AQSH, Yevropa, Hindiston, Braziliya va boshqalar. Click, Payme yoki Uzum orqali soʻmda toʻlov.',
     'Xbox Game Pass obuna kodlari: Ultimate, Premium va Essential, davlatni tanlang.',
     E'Game Pass — Microsoftning Xbox va PK uchun oʻyinlar katalogiga obunasi. Ultimate hammasini oʻz ichiga oladi: chiqqan kuni oʻyinlar, PK, bulutli oʻyin va onlayn. Premium va Essential — yengilroq tariflar.\n\nKod davlatga bogʻlangan: u shu hududdagi Microsoft akkauntida faollashadi. Akkauntingiz davlatini tanlang.\n\nClick, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.',
     E'Kodni qanday faollashtirish:\n\n1. Obuna boʻladigan Microsoft akkauntiga kiring.\n2. redeem.microsoft.com ni oching yoki Xbox da: Doʻkon → Kodni ishlatish.\n3. 25 belgili kodni kiriting va tasdiqlang.\n\nKod toʻlovdan soʻng buyurtma sahifasida chiqadi va pochtaga keladi.',
     '["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]')
  ) AS v(locale, seo_title, seo_description, short, descr, instr, hl)
 WHERE b.slug = 'xbox-game-pass' AND t.brand_id = b.id AND t.locale = v.locale;

SELECT c.region_code, s.denomination, s.price_usd::numeric(10,2), s.notice IS NOT NULL AS notice
  FROM brands c JOIN products p ON p.brand_id = c.id JOIN skus s ON s.product_id = p.id AND s.active
 WHERE c.region_parent_id = (SELECT id FROM brands WHERE slug = 'xbox-game-pass')
 ORDER BY 1, s.sort_order;

COMMIT;
