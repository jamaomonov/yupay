-- scripts/seed/2026-09-16_region_brands.sql
--
-- Split the two region-merged brands so that a brand is exactly one supplier
-- game (spec: docs/superpowers/specs/2026-09-16-brand-level-player-check-design.md,
-- ADR-0079). `mlbb-diamonds-ru` moves out of `mobile-legends` into a new
-- `mobile-legends-ru`; `mcgg-diamonds-ru` likewise into `magic-chess-gogo-ru`.
-- SKUs, mappings and sourcing rules are per SKU and do not move.
--
-- Data-only and safe on the CURRENT release: today's check is scoped to the
-- product and does not read the brand. Apply BEFORE deploying the brand-scoped
-- code — the reverse order leaves MLBB without a check between the two.
--
-- Idempotent: brand rows are inserted only when the slug is absent, the
-- product move is a no-op once done, translations upsert on (brand_id, locale),
-- FAQs on the NEW brands are rebuilt delete-then-insert, and the one FAQ added
-- to each GLOBAL brand is guarded by its question text. Wrapped in one
-- transaction. A no-op on a database that lacks the source brands (dev).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brands. Every column copied from the source brand except slug, sort_order
--    (right after the source) and timestamps. `visible_b2b` is copied on
--    purpose: MLBB is B2B-visible with 38 SKUs, and the RU half must stay so.
-- ---------------------------------------------------------------------------

INSERT INTO brands (id, slug, category_id, logo_url, hero_image_url, accent_color, sort_order, active, maintenance, visible_b2b)
SELECT gen_random_uuid(), 'mobile-legends-ru', b.category_id, b.logo_url, b.hero_image_url, b.accent_color,
       b.sort_order + 1, b.active, b.maintenance, b.visible_b2b
FROM brands b WHERE b.slug = 'mobile-legends'
  AND NOT EXISTS (SELECT 1 FROM brands WHERE slug = 'mobile-legends-ru');

INSERT INTO brands (id, slug, category_id, logo_url, hero_image_url, accent_color, sort_order, active, maintenance, visible_b2b)
SELECT gen_random_uuid(), 'magic-chess-gogo-ru', b.category_id, b.logo_url, b.hero_image_url, b.accent_color,
       b.sort_order + 1, b.active, b.maintenance, b.visible_b2b
FROM brands b WHERE b.slug = 'magic-chess-gogo'
  AND NOT EXISTS (SELECT 1 FROM brands WHERE slug = 'magic-chess-gogo-ru');

-- ---------------------------------------------------------------------------
-- 2. The products move. Everything under them (SKUs, mappings, rules) stays.
-- ---------------------------------------------------------------------------

UPDATE products SET brand_id = (SELECT id FROM brands WHERE slug = 'mobile-legends-ru'), updated_at = now()
WHERE slug = 'mlbb-diamonds-ru' AND EXISTS (SELECT 1 FROM brands WHERE slug = 'mobile-legends-ru');

UPDATE products SET brand_id = (SELECT id FROM brands WHERE slug = 'magic-chess-gogo-ru'), updated_at = now()
WHERE slug = 'mcgg-diamonds-ru' AND EXISTS (SELECT 1 FROM brands WHERE slug = 'magic-chess-gogo-ru');

-- ---------------------------------------------------------------------------
-- 3. Translations for the new brands. The region is in the name, the first
--    sentence, and the highlights — the page no longer has a second product to
--    hide it behind. `instructions` are copied from the source brand: the
--    top-up steps are the same game.
-- ---------------------------------------------------------------------------

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'ru', $n$Mobile Legends RU$n$,
    $c$["Российский аккаунт","Оплата в сумах","По ID и серверу","Без пароля"]$c$::json,
    $c$Пополнение Mobile Legends для российского аккаунта: алмазы по ID игрока и ID сервера, оплата в сумах картами Uzcard и Humo, без пароля от аккаунта. Глобальный аккаунт пополняется на отдельной странице — Mobile Legends.$c$,
    $c$Это страница для аккаунтов Mobile Legends российского региона. Алмазы зачисляются по ID игрока и ID сервера — так же, как для глобального аккаунта, но через другого поставщика, поэтому регион важен: алмазы, купленные здесь, не попадут на глобальный аккаунт, и наоборот.

Как понять, какой у вас аккаунт: если игра установлена из российского магазина и в ней рублёвые цены — вам сюда. Если цены в долларах или в другой валюте — это глобальный аккаунт, откройте страницу Mobile Legends.

Оплата картами Uzcard и Humo через Click, Payme и Uzum, в сумах. Пароль от аккаунта не нужен — только ID игрока и ID сервера из профиля.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'ru'
WHERE nb.slug = 'mobile-legends-ru' AND sb.slug = 'mobile-legends'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'en', $n$Mobile Legends RU$n$,
    $c$["Russian account","Pay in UZS","By ID and server","No password"]$c$::json,
    $c$Mobile Legends top-up for a Russian-region account: diamonds by player ID and server ID, paid in sum with Uzcard and Humo, no account password. A global account is topped up on its own page — Mobile Legends.$c$,
    $c$This page is for Mobile Legends accounts in the Russian region. Diamonds are credited by player ID and server ID, the same way as for a global account, but through a different supplier — which is why the region matters: diamonds bought here will not reach a global account, and the other way round.

How to tell which account you have: if the game was installed from the Russian store and its prices are in roubles, this is your page. If prices are in dollars or another currency, it is a global account — open the Mobile Legends page.

Pay with Uzcard and Humo via Click, Payme and Uzum, in sum. No account password is needed — just the player ID and server ID from your profile.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'en'
WHERE nb.slug = 'mobile-legends-ru' AND sb.slug = 'mobile-legends'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'uz', $n$Mobile Legends RU$n$,
    $c$["Rossiya akkaunti","Soʻmda toʻlov","ID va server boʻyicha","Parolsiz"]$c$::json,
    $c$Rossiya mintaqasidagi Mobile Legends akkaunti uchun toʻldirish: olmoslar oʻyinchi ID va server ID boʻyicha, Uzcard va Humo bilan soʻmda, akkaunt parolisiz. Global akkaunt alohida sahifada toʻldiriladi — Mobile Legends.$c$,
    $c$Bu sahifa Rossiya mintaqasidagi Mobile Legends akkauntlari uchun. Olmoslar oʻyinchi ID va server ID boʻyicha tushadi — global akkauntdagi kabi, lekin boshqa yetkazib beruvchi orqali, shuning uchun mintaqa muhim: bu yerda sotib olingan olmoslar global akkauntga tushmaydi va aksincha.

Qaysi akkaunt ekanini qanday bilish mumkin: agar oʻyin Rossiya doʻkonidan oʻrnatilgan va narxlar rublda boʻlsa — sizga shu yerga. Agar narxlar dollarda yoki boshqa valyutada boʻlsa — bu global akkaunt, Mobile Legends sahifasini oching.

Toʻlov Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan, soʻmda. Akkaunt paroli kerak emas — faqat profildagi oʻyinchi ID va server ID.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'uz'
WHERE nb.slug = 'mobile-legends-ru' AND sb.slug = 'mobile-legends'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'ru', $n$Magic Chess: Go Go RU$n$,
    $c$["Российский аккаунт","Оплата в сумах","По ID и серверу","Без пароля"]$c$::json,
    $c$Пополнение Magic Chess: Go Go для российского аккаунта: алмазы по ID игрока и ID сервера, оплата в сумах, без пароля. Глобальный аккаунт — на странице Magic Chess: Go Go.$c$,
    $c$Это страница для аккаунтов Magic Chess: Go Go российского региона. Алмазы зачисляются по ID игрока и ID сервера через поставщика российского региона, поэтому регион важен: покупка здесь не попадёт на глобальный аккаунт, и наоборот.

Как понять, какой у вас аккаунт: рублёвые цены в игре — российский, цены в долларах или другой валюте — глобальный, откройте страницу Magic Chess: Go Go.

Оплата картами Uzcard и Humo через Click, Payme и Uzum, в сумах. Пароль от аккаунта не нужен.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'ru'
WHERE nb.slug = 'magic-chess-gogo-ru' AND sb.slug = 'magic-chess-gogo'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'en', $n$Magic Chess: Go Go RU$n$,
    $c$["Russian account","Pay in UZS","By ID and server","No password"]$c$::json,
    $c$Magic Chess: Go Go top-up for a Russian-region account: diamonds by player ID and server ID, paid in sum, no password. Global accounts are on the Magic Chess: Go Go page.$c$,
    $c$This page is for Magic Chess: Go Go accounts in the Russian region. Diamonds are credited by player ID and server ID through the Russian-region supplier, so the region matters: a purchase here will not reach a global account, and the other way round.

How to tell: rouble prices in the game mean a Russian account; dollar or other-currency prices mean a global one — open the Magic Chess: Go Go page.

Pay with Uzcard and Humo via Click, Payme and Uzum, in sum. No account password is needed.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'en'
WHERE nb.slug = 'magic-chess-gogo-ru' AND sb.slug = 'magic-chess-gogo'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT nb.id, 'uz', $n$Magic Chess: Go Go RU$n$,
    $c$["Rossiya akkaunti","Soʻmda toʻlov","ID va server boʻyicha","Parolsiz"]$c$::json,
    $c$Rossiya mintaqasidagi Magic Chess: Go Go akkaunti uchun toʻldirish: olmoslar oʻyinchi ID va server ID boʻyicha, soʻmda, parolsiz. Global akkaunt — Magic Chess: Go Go sahifasida.$c$,
    $c$Bu sahifa Rossiya mintaqasidagi Magic Chess: Go Go akkauntlari uchun. Olmoslar oʻyinchi ID va server ID boʻyicha Rossiya mintaqasi yetkazib beruvchisi orqali tushadi, shuning uchun mintaqa muhim: bu yerdagi xarid global akkauntga tushmaydi va aksincha.

Qanday bilish mumkin: oʻyinda rubl narxlari — Rossiya akkaunti; dollar yoki boshqa valyuta — global, Magic Chess: Go Go sahifasini oching.

Toʻlov Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan, soʻmda. Akkaunt paroli kerak emas.$c$,
    src.instructions
FROM brands nb, brands sb JOIN brand_translations src ON src.brand_id = sb.id AND src.locale = 'uz'
WHERE nb.slug = 'magic-chess-gogo-ru' AND sb.slug = 'magic-chess-gogo'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights, short_description = EXCLUDED.short_description,
    description = EXCLUDED.description, instructions = EXCLUDED.instructions;

-- ---------------------------------------------------------------------------
-- 4. FAQ on the NEW brands: the region question first. Rebuilt each run.
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id IN (SELECT id FROM brands WHERE slug IN ('mobile-legends-ru', 'magic-chess-gogo-ru'));

WITH targets AS (
    SELECT id, slug FROM brands WHERE slug IN ('mobile-legends-ru', 'magic-chess-gogo-ru')
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), t.id, v.sort_order, true
    FROM targets t, (VALUES (1), (2)) AS v(sort_order)
    RETURNING id, brand_id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, x.locale, x.question, x.answer
FROM new_faqs nf
JOIN (
    VALUES
        (1, 'ru', $q$Как понять, российский у меня аккаунт или глобальный?$q$,
            $a$Посмотрите на цены внутри игры. Рубли — российский аккаунт, вам сюда. Доллары или другая валюта — глобальный, откройте страницу без «RU». Пополнение с неверной страницы на ваш аккаунт не попадёт.$a$),
        (1, 'en', $q$How do I know whether my account is Russian or global?$q$,
            $a$Look at the in-game prices. Roubles mean a Russian account — this page. Dollars or another currency mean a global one — open the page without "RU". A top-up from the wrong page will not reach your account.$a$),
        (1, 'uz', $q$Akkauntim Rossiya yoki globalligini qanday bilaman?$q$,
            $a$Oʻyin ichidagi narxlarga qarang. Rubl — Rossiya akkaunti, sizga shu yerga. Dollar yoki boshqa valyuta — global, «RU» siz sahifani oching. Notoʻgʻri sahifadan toʻldirish akkauntingizga tushmaydi.$a$),
        (2, 'ru', $q$Где взять ID игрока и ID сервера?$q$,
            $a$В игре откройте профиль (аватар в левом верхнем углу). Под ником — два числа в скобках: первое — ID игрока, второе — ID сервера. Кнопка «Проверить» на этой странице покажет ник по этим ID до оплаты.$a$),
        (2, 'en', $q$Where do I find the player ID and server ID?$q$,
            $a$Open your in-game profile (the avatar in the top-left corner). Under the nickname are two numbers in brackets: the first is the player ID, the second the server ID. The "Check" button on this page shows the nickname for them before you pay.$a$),
        (2, 'uz', $q$Oʻyinchi ID va server ID qayerda?$q$,
            $a$Oʻyinda profilni oching (chap yuqori burchakdagi avatar). Taxallus ostida qavsda ikkita raqam: birinchisi — oʻyinchi ID, ikkinchisi — server ID. Bu sahifadagi «Tekshirish» tugmasi toʻlovdan oldin shu ID boʻyicha taxallusni koʻrsatadi.$a$)
) AS x(sort_order, locale, question, answer) ON x.sort_order = nf.sort_order;

-- ---------------------------------------------------------------------------
-- 5. One FAQ prepended on each GLOBAL brand, pointing at its RU sibling. The
--    rest of the global FAQ is left for the owner to revise in the admin: it
--    was written for a two-products page and this file does not know its text.
-- ---------------------------------------------------------------------------

UPDATE brand_faqs SET sort_order = sort_order + 1
WHERE brand_id IN (SELECT id FROM brands WHERE slug IN ('mobile-legends', 'magic-chess-gogo'))
  AND NOT EXISTS (
      SELECT 1 FROM brand_faqs f JOIN brand_faq_translations t ON t.brand_faq_id = f.id
      WHERE f.brand_id = brand_faqs.brand_id AND t.locale = 'ru' AND t.question = $q$У меня российский аккаунт — это та страница?$q$
  );

WITH globals AS (
    SELECT id, slug FROM brands WHERE slug IN ('mobile-legends', 'magic-chess-gogo')
      AND NOT EXISTS (
          SELECT 1 FROM brand_faqs f JOIN brand_faq_translations t ON t.brand_faq_id = f.id
          WHERE f.brand_id = brands.id AND t.locale = 'ru' AND t.question = $q$У меня российский аккаунт — это та страница?$q$
      )
),
first_faq AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), g.id, 0, true FROM globals g
    RETURNING id, brand_id
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT ff.id, x.locale, x.question, x.answer
FROM first_faq ff
JOIN (
    VALUES
        ('ru', $q$У меня российский аккаунт — это та страница?$q$,
            $a$Нет. Эта страница — для глобального аккаунта (цены в игре в долларах или другой валюте). Для российского аккаунта (цены в рублях) есть отдельная страница с пометкой RU — ссылка на неё рядом с полем ID. Пополнение с неверной страницы на аккаунт не попадёт.$a$),
        ('en', $q$I have a Russian account — is this the right page?$q$,
            $a$No. This page is for a global account (in-game prices in dollars or another currency). A Russian account (rouble prices) has its own page marked RU — the link is next to the ID field. A top-up from the wrong page will not reach the account.$a$),
        ('uz', $q$Mening akkauntim Rossiya — bu oʻsha sahifami?$q$,
            $a$Yoʻq. Bu sahifa global akkaunt uchun (oʻyindagi narxlar dollarda yoki boshqa valyutada). Rossiya akkaunti (rubl narxlari) uchun RU belgili alohida sahifa bor — havola ID maydoni yonida. Notoʻgʻri sahifadan toʻldirish akkauntga tushmaydi.$a$)
) AS x(locale, question, answer) ON true;

-- ---------------------------------------------------------------------------
-- 6. Blog: the guides written for the global brand get the RU brand as a
--    related brand, so a reader of the MLBB guide sees a chip to both pages.
--    This does NOT put those guides on the RU brand page — the page's guide
--    block reads `primary_brand_id` only (blog/service.py `_brand_page`); a
--    guide for the RU page is a post of its own, or a re-primaried one.
--    `blog_post_brands` PK is (post_id, brand_id).
-- ---------------------------------------------------------------------------

INSERT INTO blog_post_brands (post_id, brand_id)
SELECT p.id, nb.id
FROM blog_posts p JOIN brands sb ON sb.id = p.primary_brand_id
JOIN brands nb ON nb.slug = sb.slug || '-ru'
WHERE sb.slug IN ('mobile-legends', 'magic-chess-gogo')
ON CONFLICT DO NOTHING;

COMMIT;
