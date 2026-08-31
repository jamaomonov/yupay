-- scripts/seed/2026-08-31_gap_products_seo.sql
--
-- Localised names + short descriptions for the four products created by
-- 2026-08-31_g2b_gap_import.py (which writes the RU name into every locale):
-- pubg-wow-coins, pubg-packs, arena-breakout-packs,
-- arena-breakout-infinite-bundles.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule.
--
-- Idempotent: rows are UPDATEd in place; re-running yields identical content.
-- Strings are dollar-quoted ($c$…$c$) so the apostrophe-heavy Uzbek copy needs
-- no escaping.

BEGIN;

-- ---------------------------------------------------------------------------
-- PUBG Mobile — WOW Coins (World of Wonder mode currency; NOT UC)
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$WOW Coins — режим World of Wonder$c$,
    short_description = $c$Валюта режима World of Wonder — платные предметы на пользовательских картах. Это отдельная валюта, не UC.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-wow-coins') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$WOW Coins — World of Wonder$c$,
    short_description = $c$Currency for the World of Wonder mode — paid items on player-made maps. A separate currency, not UC.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-wow-coins') AND locale = 'en';
UPDATE product_translations SET
    name = $c$WOW Coins — World of Wonder rejimi$c$,
    short_description = $c$World of Wonder rejimi valyutasi — oʻyinchilar yaratgan xaritalardagi pullik buyumlar uchun. Bu alohida valyuta, UC emas.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-wow-coins') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- PUBG Mobile — promo packs (rotating assortment)
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Наборы и паки$c$,
    short_description = $c$Акционные наборы PUBG Mobile: First Purchase, Weekly Deal, Mythic Emblem. Ассортимент меняется — паки могут уходить из продажи.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-packs') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Packs & bundles$c$,
    short_description = $c$PUBG Mobile promo packs: First Purchase, Weekly Deal, Mythic Emblem. Rotating stock — packs can leave the shop.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-packs') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Toʻplamlar va paketlar$c$,
    short_description = $c$PUBG Mobile aksiya toʻplamlari: First Purchase, Weekly Deal, Mythic Emblem. Assortiment oʻzgarib turadi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'pubg-packs') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- Arena Breakout — starter pack + 30-day storage cases
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Наборы и кейсы$c$,
    short_description = $c$Стартовый набор Beginner Select и хранилища на 30 дней: Bulletproof Case и Composition Case.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-packs') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Packs & cases$c$,
    short_description = $c$The Beginner Select starter pack and 30-day storage cases: Bulletproof and Composition.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-packs') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Toʻplamlar va keyslar$c$,
    short_description = $c$Beginner Select boshlangʻich toʻplami va 30 kunlik omborlar: Bulletproof Case va Composition Case.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-packs') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- Arena Breakout: Infinite — limited skin bundles
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Скин-бандлы$c$,
    short_description = $c$Наборы скинов Copper Works и Classic Craftsmanship. Ограниченные предложения — могут уходить из продажи.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-infinite-bundles') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Skin bundles$c$,
    short_description = $c$Copper Works and Classic Craftsmanship skin sets. Limited-time offers — they can leave the shop.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-infinite-bundles') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Skin toʻplamlari$c$,
    short_description = $c$Copper Works va Classic Craftsmanship skin toʻplamlari. Cheklangan takliflar — sotuvdan chiqishi mumkin.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'arena-breakout-infinite-bundles') AND locale = 'uz';

COMMIT;
