-- PlayStation, Xbox, Nintendo eShop, App Store & iTunes and Google Play on the
-- storefront: one card per platform, the countries on its region switcher
-- (ADR-0099, "A main brand that sells nothing itself").
--
-- The country brands (`playstation-us`, `xbox-tr`, `app-store-and-itunes-uk`…,
-- 122 of them) came from the bulk supplier import, priced and B2B-only. None
-- of the five has a global card, so this creates a main brand for each that
-- sells nothing itself: `playstation`, `xbox`, `nintendo`, `app-store`,
-- `google-play`. Its `region_code` ('us') names the country the page opens on;
-- the API shows that country's cards on the main page and leaves the main
-- brand off the switcher. Every country stays its own brand (SKUs, routing,
-- orders); the merchant catalogue and API are unaffected.
--
-- Not included: Xbox Game Pass and Nintendo Switch Online (subscriptions, their
-- own brands), and the single-game Xbox currencies (Apex, Halo…).
--
-- Run AFTER the release with the shelf-brand API change and the region labels;
-- before it the main pages are empty and new countries read as bare codes.
--
-- Rollback: UPDATE brands SET visible_retail = false
--   WHERE slug IN ('playstation','xbox','nintendo','app-store','google-play');
-- hides the five cards (the regions are only reachable through them).
--
-- Idempotent. Apply with operator psql:
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-11-24_platform_gift_card_regions.sql

BEGIN;

CREATE TEMP TABLE fam (slug text, prefix text, name text, sort int) ON COMMIT DROP;
INSERT INTO fam VALUES
    ('playstation', 'playstation', 'PlayStation', 25),
    ('xbox', 'xbox', 'Xbox', 26),
    ('nintendo', 'nintendo-eshop', 'Nintendo eShop', 27),
    ('app-store', 'app-store-and-itunes', 'App Store & iTunes', 28),
    ('google-play', 'google-play', 'Google Play', 29);

CREATE TEMP TABLE country (code text, ru text, en text, uz text) ON COMMIT DROP;
INSERT INTO country VALUES
    ('ae', 'ОАЭ', 'UAE', 'BAA'),
    ('ar', 'Аргентина', 'Argentina', 'Argentina'),
    ('at', 'Австрия', 'Austria', 'Avstriya'),
    ('au', 'Австралия', 'Australia', 'Avstraliya'),
    ('be', 'Бельгия', 'Belgium', 'Belgiya'),
    ('bh', 'Бахрейн', 'Bahrain', 'Bahrayn'),
    ('br', 'Бразилия', 'Brazil', 'Braziliya'),
    ('ca', 'Канада', 'Canada', 'Kanada'),
    ('ch', 'Швейцария', 'Switzerland', 'Shveytsariya'),
    ('cn', 'Китай', 'China', 'Xitoy'),
    ('co', 'Колумбия', 'Colombia', 'Kolumbiya'),
    ('cz', 'Чехия', 'Czechia', 'Chexiya'),
    ('de', 'Германия', 'Germany', 'Germaniya'),
    ('dk', 'Дания', 'Denmark', 'Daniya'),
    ('es', 'Испания', 'Spain', 'Ispaniya'),
    ('eu', 'Европа', 'Europe', 'Yevropa'),
    ('fi', 'Финляндия', 'Finland', 'Finlyandiya'),
    ('fr', 'Франция', 'France', 'Fransiya'),
    ('hk', 'Гонконг', 'Hong Kong', 'Gonkong'),
    ('hr', 'Хорватия', 'Croatia', 'Xorvatiya'),
    ('hu', 'Венгрия', 'Hungary', 'Vengriya'),
    ('id', 'Индонезия', 'Indonesia', 'Indoneziya'),
    ('ie', 'Ирландия', 'Ireland', 'Irlandiya'),
    ('in', 'Индия', 'India', 'Hindiston'),
    ('it', 'Италия', 'Italy', 'Italiya'),
    ('jp', 'Япония', 'Japan', 'Yaponiya'),
    ('kr', 'Южная Корея', 'South Korea', 'Janubiy Koreya'),
    ('kw', 'Кувейт', 'Kuwait', 'Quvayt'),
    ('lb', 'Ливан', 'Lebanon', 'Livan'),
    ('lu', 'Люксембург', 'Luxembourg', 'Lyuksemburg'),
    ('mx', 'Мексика', 'Mexico', 'Meksika'),
    ('my', 'Малайзия', 'Malaysia', 'Malayziya'),
    ('nl', 'Нидерланды', 'Netherlands', 'Niderlandiya'),
    ('no', 'Норвегия', 'Norway', 'Norvegiya'),
    ('nz', 'Новая Зеландия', 'New Zealand', 'Yangi Zelandiya'),
    ('om', 'Оман', 'Oman', 'Ummon'),
    ('pl', 'Польша', 'Poland', 'Polsha'),
    ('pt', 'Португалия', 'Portugal', 'Portugaliya'),
    ('qa', 'Катар', 'Qatar', 'Qatar'),
    ('ro', 'Румыния', 'Romania', 'Ruminiya'),
    ('ru', 'Россия', 'Russia', 'Rossiya'),
    ('sa', 'Саудовская Аравия', 'Saudi Arabia', 'Saudiya Arabistoni'),
    ('se', 'Швеция', 'Sweden', 'Shvetsiya'),
    ('sg', 'Сингапур', 'Singapore', 'Singapur'),
    ('sk', 'Словакия', 'Slovakia', 'Slovakiya'),
    ('th', 'Таиланд', 'Thailand', 'Tailand'),
    ('tr', 'Турция', 'Turkey', 'Turkiya'),
    ('uk', 'Великобритания', 'United Kingdom', 'Buyuk Britaniya'),
    ('us', 'США', 'USA', 'AQSH'),
    ('za', 'ЮАР', 'South Africa', 'Janubiy Afrika');

-- 1. The main brands: same category and logo as the US card.
INSERT INTO brands (id, slug, category_id, logo_url, sort_order, active,
                    visible_b2b, visible_retail, region_code)
SELECT gen_random_uuid(), f.slug, us.category_id, us.logo_url, f.sort, true, false, true, 'us'
  FROM fam f JOIN brands us ON us.slug = f.prefix || '-us'
ON CONFLICT (slug) DO UPDATE
   SET region_code = 'us', visible_retail = true, active = true, updated_at = now();

INSERT INTO brand_translations (brand_id, locale, name)
SELECT b.id, l.locale, f.name
  FROM fam f JOIN brands b ON b.slug = f.slug
 CROSS JOIN (VALUES ('ru'), ('en'), ('uz')) AS l(locale)
ON CONFLICT (brand_id, locale) DO UPDATE SET name = EXCLUDED.name;

-- 2. Every country brand of the family becomes a region of its main brand.
--    `xbox-game-pass-*` is excluded by the suffix being a known country code.
UPDATE brands c
   SET region_parent_id = m.id,
       region_code = k.code,
       visible_retail = true,
       updated_at = now()
  FROM fam f
  JOIN brands m ON m.slug = f.slug
  JOIN country k ON true
 WHERE c.slug = f.prefix || '-' || k.code
   AND c.active;

-- 3. "PlayStation (TR)" → "PlayStation · Турция", as on the switcher.
UPDATE brand_translations t
   SET name = f.name || ' · ' || CASE t.locale WHEN 'ru' THEN k.ru WHEN 'en' THEN k.en ELSE k.uz END
  FROM brands c
  JOIN fam f ON c.slug LIKE f.prefix || '-%'
  JOIN country k ON c.slug = f.prefix || '-' || k.code
 WHERE t.brand_id = c.id;

SELECT p.slug AS platform, p.region_code AS opens_on, count(c.id) AS regions,
       string_agg(c.region_code, ' ' ORDER BY c.region_code) AS codes
  FROM brands p
  LEFT JOIN brands c ON c.region_parent_id = p.id AND c.visible_retail
 WHERE p.slug IN (SELECT slug FROM fam)
 GROUP BY 1, 2
 ORDER BY 1;

COMMIT;
