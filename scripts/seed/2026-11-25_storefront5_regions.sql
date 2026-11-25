-- Valorant, League of Legends, Fortnite and Call of Duty Mobile on the storefront:
-- one card each with a country switcher (ADR-0099, "a main brand that sells
-- nothing itself"), plus EA SPORTS FC 26 Points and PUBG: BATTLEGROUNDS, which
-- have no countries and simply open for retail (owner, 2026-11-25).
--
-- Opens on: Valorant RU (the CIS store; owner's call), League of Legends EU,
-- Fortnite US, Call of Duty Mobile KZ (Activision regions only — the Garena
-- versions are for Southeast Asian accounts).
--
-- Run AFTER the release that adds the by/ua/kz/kh region labels, and after
-- 2026-11-25_storefront5_mapping_fixes.py.
--
-- Rollback: UPDATE brands SET visible_retail = false WHERE slug IN
--   ('valorant','league-of-legends','fortnite','call-of-duty-mobile',
--    'ea-sports-fc-26','pubg-battlegrounds');
--
-- Idempotent. Apply with operator psql.

BEGIN;

CREATE TEMP TABLE fam (slug text, prefix text, name text, opens_on text, sort int) ON COMMIT DROP;
INSERT INTO fam VALUES
    ('valorant', 'valorant-vp', 'Valorant', 'ru', 30),
    ('league-of-legends', 'league-of-legends-rp', 'League of Legends', 'eu', 31),
    ('fortnite', 'fortnite', 'Fortnite', 'us', 32),
    ('call-of-duty-mobile', 'call-of-duty-mobile-activision', 'Call of Duty: Mobile', 'kz', 33);

CREATE TEMP TABLE country (code text, ru text, en text, uz text) ON COMMIT DROP;
INSERT INTO country VALUES
    ('ae', 'ОАЭ', 'UAE', 'BAA'),
    ('ar', 'Аргентина', 'Argentina', 'Argentina'),
    ('at', 'Австрия', 'Austria', 'Avstriya'),
    ('au', 'Австралия', 'Australia', 'Avstraliya'),
    ('be', 'Бельгия', 'Belgium', 'Belgiya'),
    ('bh', 'Бахрейн', 'Bahrain', 'Bahrayn'),
    ('br', 'Бразилия', 'Brazil', 'Braziliya'),
    ('by', 'Беларусь', 'Belarus', 'Belarus'),
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
    ('kh', 'Камбоджа', 'Cambodia', 'Kambodja'),
    ('kr', 'Южная Корея', 'South Korea', 'Janubiy Koreya'),
    ('kw', 'Кувейт', 'Kuwait', 'Quvayt'),
    ('kz', 'Казахстан', 'Kazakhstan', 'Qozogʻiston'),
    ('lb', 'Ливан', 'Lebanon', 'Livan'),
    ('lu', 'Люксембург', 'Luxembourg', 'Lyuksemburg'),
    ('mx', 'Мексика', 'Mexico', 'Meksika'),
    ('my', 'Малайзия', 'Malaysia', 'Malayziya'),
    ('nl', 'Нидерланды', 'Netherlands', 'Niderlandiya'),
    ('no', 'Норвегия', 'Norway', 'Norvegiya'),
    ('nz', 'Новая Зеландия', 'New Zealand', 'Yangi Zelandiya'),
    ('om', 'Оман', 'Oman', 'Ummon'),
    ('ph', 'Филиппины', 'Philippines', 'Filippin'),
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
    ('ua', 'Украина', 'Ukraine', 'Ukraina'),
    ('uk', 'Великобритания', 'United Kingdom', 'Buyuk Britaniya'),
    ('us', 'США', 'USA', 'AQSH'),
    ('vn', 'Вьетнам', 'Vietnam', 'Vyetnam'),
    ('za', 'ЮАР', 'South Africa', 'Janubiy Afrika');

-- 1. The main brands: category and logo of the country they open on.
INSERT INTO brands (id, slug, category_id, logo_url, sort_order, active,
                    visible_b2b, visible_retail, region_code)
SELECT gen_random_uuid(), f.slug, d.category_id, d.logo_url, f.sort, true, false, true, f.opens_on
  FROM fam f JOIN brands d ON d.slug = f.prefix || '-' || f.opens_on
ON CONFLICT (slug) DO UPDATE
   SET region_code = EXCLUDED.region_code, visible_retail = true, active = true,
       updated_at = now();

INSERT INTO brand_translations (brand_id, locale, name)
SELECT b.id, l.locale, f.name
  FROM fam f JOIN brands b ON b.slug = f.slug
 CROSS JOIN (VALUES ('ru'), ('en'), ('uz')) AS l(locale)
ON CONFLICT (brand_id, locale) DO UPDATE SET name = EXCLUDED.name;

-- 2. Every country brand of the family becomes a region of its main brand.
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

-- 3. "Valorant VP (TR)" → "Valorant · Турция", as on the switcher.
UPDATE brand_translations t
   SET name = f.name || ' · ' || CASE t.locale WHEN 'ru' THEN k.ru WHEN 'en' THEN k.en ELSE k.uz END
  FROM brands c
  JOIN fam f ON c.slug LIKE f.prefix || '-%'
  JOIN country k ON c.slug = f.prefix || '-' || k.code
 WHERE t.brand_id = c.id;

-- 4. The two without countries.
UPDATE brands SET visible_retail = true, sort_order = 34, updated_at = now()
 WHERE slug = 'ea-sports-fc-26';
UPDATE brands SET visible_retail = true, sort_order = 35, updated_at = now()
 WHERE slug = 'pubg-battlegrounds';
UPDATE brand_translations t SET name = 'EA SPORTS FC 26 Points'
  FROM brands b WHERE b.id = t.brand_id AND b.slug = 'ea-sports-fc-26';

SELECT p.slug AS brand, p.region_code AS opens_on, count(c.id) AS regions,
       string_agg(c.region_code, ' ' ORDER BY c.region_code) AS codes
  FROM brands p
  LEFT JOIN brands c ON c.region_parent_id = p.id AND c.visible_retail
 WHERE p.slug IN (SELECT slug FROM fam) OR p.slug IN ('ea-sports-fc-26', 'pubg-battlegrounds')
 GROUP BY 1, 2
 ORDER BY 1;

COMMIT;
