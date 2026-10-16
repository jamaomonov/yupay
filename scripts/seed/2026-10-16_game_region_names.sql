-- Regional brands read "Game · Region" in every locale (ADR-0099).
--
-- Order pages, the bot, e-mails, the Merchant Center feed and the reseller
-- cabinet show a brand's own name. The imported names carried supplier codes
-- ("Free Fire (MY/SG)", "Magic Chess Gogo (TR)") or nothing at all. The
-- region names match the storefront switcher's labels. Main brands keep
-- their names. Slugs, and so the merchant API, do not change.
--
-- Idempotent. Apply with operator psql after the release with migration 0101:
--   sudo docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay \
--     < scripts/seed/2026-10-16_game_region_names.sql

BEGIN;

UPDATE brand_translations t
SET name = v.name
FROM (VALUES
    ('mobile-legends-ru', 'ru', 'Mobile Legends · Россия'),
    ('mobile-legends-ru', 'en', 'Mobile Legends · Russia'),
    ('mobile-legends-ru', 'uz', 'Mobile Legends · Rossiya'),
    ('mobile-legends-ph', 'ru', 'Mobile Legends · Филиппины'),
    ('mobile-legends-ph', 'en', 'Mobile Legends · Philippines'),
    ('mobile-legends-ph', 'uz', 'Mobile Legends · Filippin'),
    ('mobile-legends-my', 'ru', 'Mobile Legends · Малайзия'),
    ('mobile-legends-my', 'en', 'Mobile Legends · Malaysia'),
    ('mobile-legends-my', 'uz', 'Mobile Legends · Malayziya'),
    ('mobile-legends-sg', 'ru', 'Mobile Legends · Сингапур'),
    ('mobile-legends-sg', 'en', 'Mobile Legends · Singapore'),
    ('mobile-legends-sg', 'uz', 'Mobile Legends · Singapur'),
    ('mobile-legends-id', 'ru', 'Mobile Legends · Индонезия'),
    ('mobile-legends-id', 'en', 'Mobile Legends · Indonesia'),
    ('mobile-legends-id', 'uz', 'Mobile Legends · Indoneziya'),
    ('mobile-legends-tr', 'ru', 'Mobile Legends · Турция'),
    ('mobile-legends-tr', 'en', 'Mobile Legends · Turkey'),
    ('mobile-legends-tr', 'uz', 'Mobile Legends · Turkiya'),
    ('mobile-legends-us', 'ru', 'Mobile Legends · США'),
    ('mobile-legends-us', 'en', 'Mobile Legends · USA'),
    ('mobile-legends-us', 'uz', 'Mobile Legends · AQSH'),
    ('mobile-legends-br', 'ru', 'Mobile Legends · Бразилия'),
    ('mobile-legends-br', 'en', 'Mobile Legends · Brazil'),
    ('mobile-legends-br', 'uz', 'Mobile Legends · Braziliya'),
    ('magic-chess-gogo-ru', 'ru', 'Magic Chess: Go Go · Россия'),
    ('magic-chess-gogo-ru', 'en', 'Magic Chess: Go Go · Russia'),
    ('magic-chess-gogo-ru', 'uz', 'Magic Chess: Go Go · Rossiya'),
    ('magic-chess-gogo-my', 'ru', 'Magic Chess: Go Go · Малайзия'),
    ('magic-chess-gogo-my', 'en', 'Magic Chess: Go Go · Malaysia'),
    ('magic-chess-gogo-my', 'uz', 'Magic Chess: Go Go · Malayziya'),
    ('magic-chess-gogo-ph', 'ru', 'Magic Chess: Go Go · Филиппины'),
    ('magic-chess-gogo-ph', 'en', 'Magic Chess: Go Go · Philippines'),
    ('magic-chess-gogo-ph', 'uz', 'Magic Chess: Go Go · Filippin'),
    ('magic-chess-gogo-tr', 'ru', 'Magic Chess: Go Go · Турция'),
    ('magic-chess-gogo-tr', 'en', 'Magic Chess: Go Go · Turkey'),
    ('magic-chess-gogo-tr', 'uz', 'Magic Chess: Go Go · Turkiya'),
    ('garena-free-fire', 'ru', 'Free Fire · Глобальный'),
    ('garena-free-fire', 'en', 'Free Fire · Global'),
    ('garena-free-fire', 'uz', 'Free Fire · Global'),
    ('free-fire-bd', 'ru', 'Free Fire · Бангладеш'),
    ('free-fire-bd', 'en', 'Free Fire · Bangladesh'),
    ('free-fire-bd', 'uz', 'Free Fire · Bangladesh'),
    ('free-fire-br', 'ru', 'Free Fire · Бразилия'),
    ('free-fire-br', 'en', 'Free Fire · Brazil'),
    ('free-fire-br', 'uz', 'Free Fire · Braziliya'),
    ('free-fire-eu', 'ru', 'Free Fire · Европа'),
    ('free-fire-eu', 'en', 'Free Fire · Europe'),
    ('free-fire-eu', 'uz', 'Free Fire · Yevropa'),
    ('free-fire-id', 'ru', 'Free Fire · Индонезия'),
    ('free-fire-id', 'en', 'Free Fire · Indonesia'),
    ('free-fire-id', 'uz', 'Free Fire · Indoneziya'),
    ('free-fire-latam', 'ru', 'Free Fire · Латинская Америка'),
    ('free-fire-latam', 'en', 'Free Fire · Latin America'),
    ('free-fire-latam', 'uz', 'Free Fire · Lotin Amerikasi'),
    ('free-fire-mena', 'ru', 'Free Fire · Ближний Восток'),
    ('free-fire-mena', 'en', 'Free Fire · Middle East'),
    ('free-fire-mena', 'uz', 'Free Fire · Yaqin Sharq'),
    ('free-fire-my-sg', 'ru', 'Free Fire · Малайзия и Сингапур'),
    ('free-fire-my-sg', 'en', 'Free Fire · Malaysia & Singapore'),
    ('free-fire-my-sg', 'uz', 'Free Fire · Malayziya va Singapur'),
    ('free-fire-ph', 'ru', 'Free Fire · Филиппины'),
    ('free-fire-ph', 'en', 'Free Fire · Philippines'),
    ('free-fire-ph', 'uz', 'Free Fire · Filippin'),
    ('free-fire-sg', 'ru', 'Free Fire · Сингапур'),
    ('free-fire-sg', 'en', 'Free Fire · Singapore'),
    ('free-fire-sg', 'uz', 'Free Fire · Singapur'),
    ('free-fire-th', 'ru', 'Free Fire · Таиланд'),
    ('free-fire-th', 'en', 'Free Fire · Thailand'),
    ('free-fire-th', 'uz', 'Free Fire · Tailand'),
    ('free-fire-tw', 'ru', 'Free Fire · Тайвань'),
    ('free-fire-tw', 'en', 'Free Fire · Taiwan'),
    ('free-fire-tw', 'uz', 'Free Fire · Tayvan'),
    ('free-fire-vn', 'ru', 'Free Fire · Вьетнам'),
    ('free-fire-vn', 'en', 'Free Fire · Vietnam'),
    ('free-fire-vn', 'uz', 'Free Fire · Vyetnam')
) AS v(slug, locale, name)
JOIN brands b ON b.slug = v.slug
WHERE t.brand_id = b.id AND t.locale = v.locale;

SELECT b.slug, t.locale, t.name
FROM brands b JOIN brand_translations t ON t.brand_id = b.id
WHERE b.region_parent_id IS NOT NULL AND t.locale = 'ru'
ORDER BY 1;

COMMIT;
