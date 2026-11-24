-- Roblox regional gift cards on the storefront, as regions of `roblox` (ADR-0099).
--
-- The 25 `roblox-xx` brands came from the bulk supplier import, priced and
-- B2B-only, each its own brand. This links each one to `roblox` with its region
-- code and makes it retail-visible: the storefront keeps one Roblox card, and
-- the `/store/roblox` page gets a region switcher, the same way Free Fire's
-- regions work. Each region stays its own brand (own SKUs, routing, orders);
-- the merchant catalogue and API are unaffected.
--
-- Run AFTER the release that knows the new region codes (REGION_ORDER and the
-- switcher labels for uk/ca/au/nz/jp/hk/ae/sa/mx/za/fr/at/ch/dk/no/se/pl):
-- before it, those chips read as bare codes ("UK") and sort last.
--
-- Names: "Roblox (UK)" → "Roblox · Великобритания", matching the switcher,
-- for order pages, the bot, e-mails and the reseller cabinet. Slugs unchanged.
--
-- Rollback for one region: UPDATE brands SET visible_retail = false WHERE slug = 'roblox-xx';
-- For all: the same with slug LIKE 'roblox-%' (the link can stay, it is inert
-- while the brand is not retail-visible).
--
-- Idempotent. Apply with operator psql:
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-11-24_roblox_regions.sql

BEGIN;

UPDATE brands c
SET region_parent_id = m.id, region_code = v.code, visible_retail = true, updated_at = now()
FROM (VALUES
    ('roblox-ae', 'ae'),
    ('roblox-at', 'at'),
    ('roblox-au', 'au'),
    ('roblox-br', 'br'),
    ('roblox-ca', 'ca'),
    ('roblox-ch', 'ch'),
    ('roblox-dk', 'dk'),
    ('roblox-eu', 'eu'),
    ('roblox-fr', 'fr'),
    ('roblox-hk', 'hk'),
    ('roblox-id', 'id'),
    ('roblox-jp', 'jp'),
    ('roblox-mx', 'mx'),
    ('roblox-my', 'my'),
    ('roblox-no', 'no'),
    ('roblox-nz', 'nz'),
    ('roblox-pl', 'pl'),
    ('roblox-ru', 'ru'),
    ('roblox-sa', 'sa'),
    ('roblox-se', 'se'),
    ('roblox-sg', 'sg'),
    ('roblox-th', 'th'),
    ('roblox-uk', 'uk'),
    ('roblox-us', 'us'),
    ('roblox-za', 'za')
) AS v(slug, code), brands m
WHERE c.slug = v.slug AND m.slug = 'roblox' AND m.region_parent_id IS NULL;

UPDATE brand_translations t
SET name = v.name
FROM (VALUES
    ('roblox-ae', 'ru', 'Roblox · ОАЭ'),
    ('roblox-ae', 'en', 'Roblox · UAE'),
    ('roblox-ae', 'uz', 'Roblox · BAA'),
    ('roblox-at', 'ru', 'Roblox · Австрия'),
    ('roblox-at', 'en', 'Roblox · Austria'),
    ('roblox-at', 'uz', 'Roblox · Avstriya'),
    ('roblox-au', 'ru', 'Roblox · Австралия'),
    ('roblox-au', 'en', 'Roblox · Australia'),
    ('roblox-au', 'uz', 'Roblox · Avstraliya'),
    ('roblox-br', 'ru', 'Roblox · Бразилия'),
    ('roblox-br', 'en', 'Roblox · Brazil'),
    ('roblox-br', 'uz', 'Roblox · Braziliya'),
    ('roblox-ca', 'ru', 'Roblox · Канада'),
    ('roblox-ca', 'en', 'Roblox · Canada'),
    ('roblox-ca', 'uz', 'Roblox · Kanada'),
    ('roblox-ch', 'ru', 'Roblox · Швейцария'),
    ('roblox-ch', 'en', 'Roblox · Switzerland'),
    ('roblox-ch', 'uz', 'Roblox · Shveytsariya'),
    ('roblox-dk', 'ru', 'Roblox · Дания'),
    ('roblox-dk', 'en', 'Roblox · Denmark'),
    ('roblox-dk', 'uz', 'Roblox · Daniya'),
    ('roblox-eu', 'ru', 'Roblox · Европа'),
    ('roblox-eu', 'en', 'Roblox · Europe'),
    ('roblox-eu', 'uz', 'Roblox · Yevropa'),
    ('roblox-fr', 'ru', 'Roblox · Франция'),
    ('roblox-fr', 'en', 'Roblox · France'),
    ('roblox-fr', 'uz', 'Roblox · Fransiya'),
    ('roblox-hk', 'ru', 'Roblox · Гонконг'),
    ('roblox-hk', 'en', 'Roblox · Hong Kong'),
    ('roblox-hk', 'uz', 'Roblox · Gonkong'),
    ('roblox-id', 'ru', 'Roblox · Индонезия'),
    ('roblox-id', 'en', 'Roblox · Indonesia'),
    ('roblox-id', 'uz', 'Roblox · Indoneziya'),
    ('roblox-jp', 'ru', 'Roblox · Япония'),
    ('roblox-jp', 'en', 'Roblox · Japan'),
    ('roblox-jp', 'uz', 'Roblox · Yaponiya'),
    ('roblox-mx', 'ru', 'Roblox · Мексика'),
    ('roblox-mx', 'en', 'Roblox · Mexico'),
    ('roblox-mx', 'uz', 'Roblox · Meksika'),
    ('roblox-my', 'ru', 'Roblox · Малайзия'),
    ('roblox-my', 'en', 'Roblox · Malaysia'),
    ('roblox-my', 'uz', 'Roblox · Malayziya'),
    ('roblox-no', 'ru', 'Roblox · Норвегия'),
    ('roblox-no', 'en', 'Roblox · Norway'),
    ('roblox-no', 'uz', 'Roblox · Norvegiya'),
    ('roblox-nz', 'ru', 'Roblox · Новая Зеландия'),
    ('roblox-nz', 'en', 'Roblox · New Zealand'),
    ('roblox-nz', 'uz', 'Roblox · Yangi Zelandiya'),
    ('roblox-pl', 'ru', 'Roblox · Польша'),
    ('roblox-pl', 'en', 'Roblox · Poland'),
    ('roblox-pl', 'uz', 'Roblox · Polsha'),
    ('roblox-ru', 'ru', 'Roblox · Россия'),
    ('roblox-ru', 'en', 'Roblox · Russia'),
    ('roblox-ru', 'uz', 'Roblox · Rossiya'),
    ('roblox-sa', 'ru', 'Roblox · Саудовская Аравия'),
    ('roblox-sa', 'en', 'Roblox · Saudi Arabia'),
    ('roblox-sa', 'uz', 'Roblox · Saudiya Arabistoni'),
    ('roblox-se', 'ru', 'Roblox · Швеция'),
    ('roblox-se', 'en', 'Roblox · Sweden'),
    ('roblox-se', 'uz', 'Roblox · Shvetsiya'),
    ('roblox-sg', 'ru', 'Roblox · Сингапур'),
    ('roblox-sg', 'en', 'Roblox · Singapore'),
    ('roblox-sg', 'uz', 'Roblox · Singapur'),
    ('roblox-th', 'ru', 'Roblox · Таиланд'),
    ('roblox-th', 'en', 'Roblox · Thailand'),
    ('roblox-th', 'uz', 'Roblox · Tailand'),
    ('roblox-uk', 'ru', 'Roblox · Великобритания'),
    ('roblox-uk', 'en', 'Roblox · United Kingdom'),
    ('roblox-uk', 'uz', 'Roblox · Buyuk Britaniya'),
    ('roblox-us', 'ru', 'Roblox · США'),
    ('roblox-us', 'en', 'Roblox · USA'),
    ('roblox-us', 'uz', 'Roblox · AQSH'),
    ('roblox-za', 'ru', 'Roblox · ЮАР'),
    ('roblox-za', 'en', 'Roblox · South Africa'),
    ('roblox-za', 'uz', 'Roblox · Janubiy Afrika')
) AS v(slug, locale, name), brands b
WHERE b.slug = v.slug AND t.brand_id = b.id AND t.locale = v.locale;

SELECT c.region_code, c.slug, c.visible_retail,
       (SELECT name FROM brand_translations WHERE brand_id = c.id AND locale = 'ru') AS ru_name
FROM brands c JOIN brands p ON p.id = c.region_parent_id
WHERE p.slug = 'roblox'
ORDER BY 1;

COMMIT;
