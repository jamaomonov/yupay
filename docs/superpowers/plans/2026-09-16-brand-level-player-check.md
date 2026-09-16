# Brand-Level Player Check & Region Brands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a brand exactly one supplier game, bind the player-id check to the brand (customers check before picking a package; resellers send a brand slug), and split `mobile-legends` / `magic-chess-gogo` into global + RU brands so the invariant holds.

**Architecture:** The catalog split is a data-only, idempotent SQL seed applied to prod _before_ the code deploys (today's product-scoped check does not care which brand a product sits in). The API gains a brand-scoped resolver that refuses — never guesses — when a brand's active `g2b/game` mappings span two codes, a public `POST /catalog/brands/{slug}/check-player` replacing the product one, and a merchant `validate/player` that takes `brand`. The storefront keys verdicts by brand slug, drops the "pick a package first" gate, and shows a sibling-region link on the two split brands.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async), pytest + respx; Next.js 15 + Vitest + Testing Library; Postgres seed SQL applied with `psql -v ON_ERROR_STOP=1`.

**Spec:** `docs/superpowers/specs/2026-09-16-brand-level-player-check-design.md`

## Global Constraints

- Check stays **advisory and never a fake rejecter** (ADR-0031): every fault → `status="error"`; two games behind one brand → `error`, never a guess.
- Only `valid` verdicts are cached (`_worth_caching`, commit `40253743`); cache key `playercheck:g2b:{game_code}:{server|-}:{player_id_hash}` is unchanged.
- No PII in logs: `player_id` / `steam_login` only as `hash_short(...)`; brand ids and slugs are fine.
- `mobile-legends` and `magic-chess-gogo` keep their slugs. New slugs: `mobile-legends-ru`, `magic-chess-gogo-ru`. Names: "Mobile Legends RU", "Magic Chess: Go Go RU" (identical in ru/en/uz).
- Merchant body: `{brand, player_id, server_id?}`; `sku_id` is **removed** (0 live traffic), `extra="forbid"` stays.
- Every new user-facing string lands in `ru`, `en`, `uz` in the same commit; the i18n parity check in CI fails otherwise.
- Python: ruff (line 100) + mypy --strict, Google docstrings, no `Any` without a comment. TS: strict, no `any`, no `as` except narrowing a known JSON shape.
- Run from repo root. Python: `uv run pytest …`. Web: `pnpm --filter @yupay/web exec vitest run …`. Before pushing: `pnpm exec prettier --check .`.
- Commit messages: Conventional Commits, scope = module. Never push or deploy without the owner's explicit command.

---

### Task 1: The region-brand seed

**Files:**

- Create: `scripts/seed/2026-09-16_region_brands.sql`

**Interfaces:**

- Produces: brands `mobile-legends-ru`, `magic-chess-gogo-ru`; products `mlbb-diamonds-ru` → `mobile-legends-ru`, `mcgg-diamonds-ru` → `magic-chess-gogo-ru`. No column changes. Later tasks assume these slugs exist on prod at rollout time only (§ Rollout); tests never depend on them.

- [ ] **Step 1: Write the seed**

```sql
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
-- 6. Blog: whatever guides are attached to the global brand also show on the
--    RU one. `blog_post_brands` PK is (post_id, brand_id).
-- ---------------------------------------------------------------------------

INSERT INTO blog_post_brands (post_id, brand_id)
SELECT p.id, nb.id
FROM blog_posts p JOIN brands sb ON sb.id = p.primary_brand_id
JOIN brands nb ON nb.slug = sb.slug || '-ru'
WHERE sb.slug IN ('mobile-legends', 'magic-chess-gogo')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply to the dev database twice and read it back**

Run (dev has the source brands only if it was seeded with them; the file is a no-op otherwise — say so in your report if the counts below come back empty):

```bash
docker exec -i yupay-dev-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 < scripts/seed/2026-09-16_region_brands.sql
docker exec -i yupay-dev-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 < scripts/seed/2026-09-16_region_brands.sql
docker exec yupay-dev-postgres-1 psql -U yupay_app -d yupay -tAc "
SELECT b.slug, count(p.id) FROM brands b LEFT JOIN products p ON p.brand_id=b.id
WHERE b.slug IN ('mobile-legends','mobile-legends-ru','magic-chess-gogo','magic-chess-gogo-ru') GROUP BY b.slug ORDER BY 1;
SELECT b.slug, count(*) FROM brand_faqs f JOIN brands b ON b.id=f.brand_id
WHERE b.slug IN ('mobile-legends','mobile-legends-ru','magic-chess-gogo','magic-chess-gogo-ru') GROUP BY b.slug ORDER BY 1;"
```

Expected: both runs end with `COMMIT`; if the source brands exist, `mobile-legends|1`, `mobile-legends-ru|1`, `magic-chess-gogo|1`, `magic-chess-gogo-ru|1`; each RU brand has 2 FAQs; each global brand has one more FAQ than before and only one titled «У меня российский аккаунт — это та страница?».

- [ ] **Step 3: Commit**

```bash
git add scripts/seed/2026-09-16_region_brands.sql
git commit -m "feat(catalog): seed the MLBB and MCGG region brands

Data-only split so that a brand is one supplier game (ADR-0079, supersedes
ADR-0048). Idempotent; a no-op where the source brands are absent. Applied to
prod by an operator BEFORE the brand-scoped check deploys."
```

---

### Task 2: Brand-scoped resolver and `check_player_for_brand`

**Files:**

- Modify: `apps/api/src/yupay/modules/integrations/player_check.py`
- Modify: `apps/api/src/yupay/modules/integrations/api.py` (line 10 import and the `__all__` entry at line 71: `check_player_for_product` → `check_player_for_brand`)
- Test: `apps/api/tests/unit/test_player_check_service.py`, `apps/api/tests/integration/test_player_check_endpoint.py` (fixtures only in this task)

**Interfaces:**

- Consumes: `Brand`, `Product`, `Sku` (`yupay.modules.catalog.models`), `SkuSupplierMapping`, existing `_check_waxpeer_login`, `_checkable_provider`, `_cache_key`, `_cached`, `_breaker_for_g2b`, `_map_response`.
- Produces:
  - `CODE_BRAND_NOT_FOUND = "brand_not_found"`
  - `brand_check_field(session, brand_id) -> dict[str, Any] | None` — the one `check`-bearing form field the brand's active products agree on, or `None` (not checkable, or misconfigured).
  - `resolve_g2b_game_code(session, brand_id) -> str | None` — **brand**-scoped now.
  - `check_player_for_brand(session, *, brand_slug, player_id, server_id) -> PlayerCheckOut` — raises `NotFoundError(code=CODE_BRAND_NOT_FOUND)` / `ValidationError("brand is not checkable")`; never raises for supplier faults.
  - `check_player_for_brand_id(session, *, brand_id, player_id, server_id) -> PlayerCheckOut` — same, for a caller that already resolved the brand (Task 4).
  - `check_player_for_product` and product-scoped `resolve_g2b_game_code` are **deleted**; `product_is_checkable` stays.

- [ ] **Step 1: Write the failing unit tests**

Append to `apps/api/tests/unit/test_player_check_service.py`:

```python
def test_brand_check_field_needs_a_check_on_some_product() -> None:
    assert pc._field_of([{"key": "email", "type": "text"}]) is None
    f = pc._field_of([{"key": "player_id", "type": "text", "check": {"provider": "g2b"}}])
    assert f is not None and f["key"] == "player_id"


def test_brand_check_fields_must_agree_across_products() -> None:
    """Two products of one brand declaring different checks is a misconfiguration:
    a brand-level check would have to pick one, and picking is guessing."""
    a = {"key": "player_id", "type": "text", "check": {"provider": "g2b"}}
    b = {"key": "player_id", "type": "text", "check": {"provider": "g2b", "server_field": "server"}}
    assert pc._agreed_field([a, a]) is a
    assert pc._agreed_field([a, b]) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/api/tests/unit/test_player_check_service.py -q -k "brand_check"`
Expected: FAIL — `AttributeError: module ... has no attribute '_field_of'`.

- [ ] **Step 3: Implement the resolver and the brand entry points**

In `player_check.py`, add after `product_is_checkable`:

```python
def _field_of(required_fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The first form field that opts into a supported check, or ``None``."""
    for f in required_fields:
        if isinstance(f, dict) and isinstance(f.get("check"), dict):
            if f["check"].get("provider") in _KNOWN_PROVIDERS:
                return f
    return None


def _agreed_field(fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One check config every product of a brand agrees on, or ``None``.

    Agreement is on the three things the check actually reads: provider, the
    sibling server field and the id field's key. Anything else differing
    between products (labels, patterns) does not change what is checked.
    """
    if not fields:
        return None
    first = fields[0]

    def _sig(f: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (f["check"].get("provider"), f["check"].get("server_field"), f.get("key"))

    return first if all(_sig(f) == _sig(first) for f in fields[1:]) else None


async def brand_check_field(session: AsyncSession, brand_id: str) -> dict[str, Any] | None:
    """The check-bearing form field of a brand, or ``None``.

    ``None`` covers both "no product of this brand declares a check" and
    "its products disagree on the check" — the second is logged, because it is
    a catalog mistake someone has to fix, not a brand that never wanted one.

    Columns, not entities: ``Product`` configures selectin relationships that
    would drag the whole retail subtree through an advisory lookup.
    """
    rows = (
        await session.execute(
            select(Product.required_fields).where(
                Product.brand_id == brand_id, Product.active.is_(True)
            )
        )
    ).all()
    fields = [f for (rf,) in rows if (f := _field_of(list(rf or []))) is not None]
    if not fields:
        return None
    agreed = _agreed_field(fields)
    if agreed is None:
        logger.warning(
            "player_check_brand_config_mismatch",
            brand_id=brand_id,
            hint="the brand's products declare different `check` configs; a brand "
            "is one game (ADR-0079), so they must agree — no check until they do",
        )
    return agreed
```

Replace the product-scoped `resolve_g2b_game_code` with:

```python
async def resolve_g2b_game_code(session: AsyncSession, brand_id: str) -> str | None:
    """The G2B game_code for a brand = the one ``external_product_id`` across
    its active ``g2b/game`` mappings.

    A brand is exactly one supplier game (ADR-0079). Two distinct codes means
    the catalog is mid-migration or misconfigured, and picking one would
    validate a player against the wrong region's game and answer "invalid"
    for a perfectly good id — so two codes is no check rather than a wrong one.
    """
    stmt = (
        select(SkuSupplierMapping.external_product_id)
        .join(Sku, Sku.id == SkuSupplierMapping.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .where(
            Product.brand_id == brand_id,
            SkuSupplierMapping.supplier_slug == "g2b",
            SkuSupplierMapping.kind == "game",
            SkuSupplierMapping.is_active.is_(True),
        )
        .distinct()
        .limit(2)
    )
    codes = list((await session.execute(stmt)).scalars().all())
    if len(codes) > 1:
        logger.warning(
            "player_check_brand_spans_games",
            brand_id=brand_id,
            codes=sorted(codes),
            hint="one brand maps to two G2B games; split it (see ADR-0079) — "
            "every check on it answers `error` until then",
        )
        return None
    if not codes:
        logger.warning(
            "player_check_no_game_mapping",
            brand_id=brand_id,
            hint="this brand's form declares a g2b player check but no active "
            "sku_supplier_mapping (supplier_slug='g2b', kind='game') exists on any "
            "of its SKUs, so every check answers `error`; add the mapping or drop the "
            "check from the form",
        )
        return None
    return codes[0]
```

Replace `check_player_for_product` with:

```python
CODE_BRAND_NOT_FOUND = "brand_not_found"


async def check_player_for_brand(
    session: AsyncSession,
    *,
    brand_slug: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """Verify a player id (or Steam login) for a brand. Never raises on a
    supplier fault; raises only for a brand that does not exist or is not
    checkable, which are the caller's mistakes.

    Args:
        session: Session. Rolled back before a Waxpeer call, as before.
        brand_slug: The brand's public slug, as in ``/catalog/brands``.
        player_id: The customer's identifier — never logged, only hashed.
        server_id: The sibling server value, where the form declares one.

    Returns:
        The three-way advisory verdict.
    """
    row = (
        await session.execute(
            select(Brand.id).where(Brand.slug == brand_slug, Brand.active.is_(True))
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("brand not found", code=CODE_BRAND_NOT_FOUND)
    return await check_player_for_brand_id(
        session, brand_id=row.id, player_id=player_id, server_id=server_id
    )


async def check_player_for_brand_id(
    session: AsyncSession,
    *,
    brand_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """As :func:`check_player_for_brand`, for a caller that already has the id."""
    from yupay.modules.integrations.routes import _waxpeer_fulfiller_or_none

    field = await brand_check_field(session, brand_id)
    if field is None:
        raise ValidationError("brand is not checkable")
    if field["check"]["provider"] == "waxpeer":
        await session.rollback()
        return await _check_waxpeer_login(_waxpeer_fulfiller_or_none(), steam_login=player_id)
    return await _check_g2b_player(
        session, brand_id=brand_id, player_id=player_id, server_id=server_id
    )
```

In `_check_g2b_player`, change the signature `product_id: str` → `brand_id: str` and the first line to `game_code = await resolve_g2b_game_code(session, brand_id)`. Add `Brand` to the `yupay.modules.catalog.models` import. Delete the now-unused `uuid` import and `CODE_PRODUCT_NOT_FOUND` (grep first: `grep -rn CODE_PRODUCT_NOT_FOUND apps/api/src` — it is also referenced in `merchants/validate.py` docs only via `quote.unavailable`, not imported; if a reference remains, keep the constant).

In `integrations/api.py` change the import on line 10 and the `__all__` entry to `check_player_for_brand` (the facade re-exports the public entry point; nothing else in the repo imports the old name through it — `rg check_player_for_product apps` after this task must list only `merchants/validate.py` and the two routes files that Tasks 3–4 rewrite).

- [ ] **Step 4: Run the unit tests**

Run: `uv run pytest apps/api/tests/unit/test_player_check_service.py -q`
Expected: all pass (the two new ones and the existing key/verdict tests).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff format apps/api/src/yupay/modules/integrations/player_check.py && uv run ruff check apps/api/src/yupay/modules/integrations && uv run mypy apps/api/src`
Expected: clean. (Callers of the deleted `check_player_for_product` — `integrations/routes.py`, `merchants/validate.py` — will fail mypy until Tasks 3–4; run mypy again at the end of Task 4.)

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/integrations/player_check.py apps/api/src/yupay/modules/integrations/api.py apps/api/tests/unit/test_player_check_service.py
git commit -m "feat(integrations): resolve the player check by brand, refuse when a brand spans two games"
```

---

### Task 3: Public route `POST /catalog/brands/{slug}/check-player`

**Files:**

- Modify: `apps/api/src/yupay/modules/integrations/routes.py` (the `router.post("/products/{product_id}/check-player")` block, ~lines 68–88)
- Modify: `apps/api/tests/integration/test_player_check_endpoint.py`
- Modify: `AGENTS.md` (lines ~244 and ~284–286), `apps/api/src/yupay/modules/integrations/README.md`

**Interfaces:**

- Consumes: `check_player_for_brand` (Task 2).
- Produces: `POST /api/v1/catalog/brands/{slug}/check-player` — body `PlayerCheckIn`, response `PlayerCheckOut`, rate bucket `check_player`, no `Idempotency-Key`. The product route is gone (404).

- [ ] **Step 1: Rewrite the endpoint tests first**

In `test_player_check_endpoint.py`:

1. Replace every `f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player"` with `"/api/v1/catalog/brands/pubgm-check/check-player"`, every `seed_waxpeer_product`-based URL with `"/api/v1/catalog/brands/steam-wallet-check/check-player"`, and the plain one with `"/api/v1/catalog/brands/steam-plain-check/check-player"`. Keep the fixtures (they still seed the brands with those slugs).
2. Rewrite `test_unknown_product_404`:

```python
async def test_unknown_brand_404(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/catalog/brands/no-such-brand/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "brand_not_found"
```

3. Replace `test_two_game_codes_on_one_product_check_nothing` with a brand that spans two games:

```python
@pytest.fixture
async def seed_split_brand(db_session: AsyncSession) -> str:
    """One brand, two products, two G2B games — the pre-ADR-0079 MLBB shape."""
    category = Category(id=new_id(), slug="games-split-check", sort_order=10, active=True,
                        translations=[CategoryTranslation(locale="ru", name="Игры")])
    brand = Brand(id=new_id(), slug="mlbb-split-check", category_id=category.id, sort_order=10,
                  active=True, translations=[BrandTranslation(locale="ru", name="MLBB")])
    field = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text", "check": {"provider": "g2b"}}]
    products = [
        Product(id=new_id(), slug=f"mlbb-{tag}-check", brand_id=brand.id, kind="top_up", sort_order=i,
                active=True, required_fields=field,
                translations=[ProductTranslation(locale="ru", name=f"MLBB {tag}")])
        for i, tag in enumerate(("global", "ru"))
    ]
    skus = [
        Sku(id=new_id(), product_id=p.id, sku_code=f"mlbb-{p.slug}-60", denomination="60",
            region="WW", price_usd=Decimal("1.00"), sort_order=1, active=True)
        for p in products
    ]
    db_session.add_all([category, brand, *products, *skus])
    await db_session.commit()
    db_session.add_all([
        SkuSupplierMapping(sku_id=skus[0].id, supplier_slug="g2b", kind="game",
                           external_product_id="mlbb", external_variant_id="60", is_active=True),
        SkuSupplierMapping(sku_id=skus[1].id, supplier_slug="g2b", kind="game",
                           external_product_id="mlbb_ru", external_variant_id="60", is_active=True),
    ])
    await db_session.commit()
    return brand.slug


@respx.mock
async def test_a_brand_spanning_two_games_checks_nothing(
    client: httpx.AsyncClient, seed_split_brand: str
) -> None:
    """Picking one of two games would validate a player against the wrong
    region and call a good id `invalid`. The only honest answer is `error`."""
    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    with structlog.testing.capture_logs() as logs:
        r = await client.post(
            f"/api/v1/catalog/brands/{seed_split_brand}/check-player",
            json={"player_id": "51234567"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert not route.called, "no supplier call on an ambiguous brand"
    assert any(e["event"] == "player_check_brand_spans_games" for e in logs)
```

(Add `import structlog.testing` next to the other imports if it is not already there; the merchant validate tests import it the same way.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest apps/api/tests/integration/test_player_check_endpoint.py -q`
Expected: FAIL — 404s on the brand URLs (route does not exist yet).

- [ ] **Step 3: Swap the route**

In `integrations/routes.py` replace the whole `check_player` handler and its decorator with:

```python
@router.post(
    "/brands/{slug}/check-player",
    response_model=PlayerCheckOut,
    summary="Verify a player id for a brand (advisory nickname lookup)",
)
async def check_player(
    slug: str,
    body: PlayerCheckIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PlayerCheckOut:
    """Storefront-facing. Advisory — folds upstream errors into
    ``status="error"``; never blocks checkout. Rate-limited per IP. See
    ADR-0031 and ADR-0079 (why a brand: a brand is one game).
    """
    await guard_ip(request, bucket="check_player")
    return await check_player_for_brand(
        db, brand_slug=slug, player_id=body.player_id, server_id=body.server_id
    )
```

and change the import `check_player_for_product` → `check_player_for_brand`.

- [ ] **Step 4: Run the endpoint tests**

Run: `uv run pytest apps/api/tests/integration/test_player_check_endpoint.py -q`
Expected: all pass.

- [ ] **Step 5: Update AGENTS.md and the module README**

In `AGENTS.md`, in both places, replace the text `POST /catalog/products/{id}/check-player` with `POST /catalog/brands/{slug}/check-player`. In `apps/api/src/yupay/modules/integrations/README.md`, wherever the product endpoint or `check_player_for_product` is named, replace with the brand endpoint / `check_player_for_brand`, and add one sentence under the player-check section: "A brand is one supplier game (ADR-0079); a brand whose active g2b/game mappings span two codes answers `error` and logs `player_check_brand_spans_games`."

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/integrations/routes.py apps/api/tests/integration/test_player_check_endpoint.py AGENTS.md apps/api/src/yupay/modules/integrations/README.md
git commit -m "feat(integrations): expose the player check per brand, retire the product route"
```

---

### Task 4: Merchant `validate/player` takes a brand

**Files:**

- Modify: `apps/api/src/yupay/modules/merchants/machine_schemas.py` (`MerchantPlayerCheckIn`, ~lines 636–668)
- Modify: `apps/api/src/yupay/modules/merchants/validate.py` (`_checkable_product` → `_checkable_brand`, `check_player`)
- Modify: `apps/api/src/yupay/modules/merchants/api.py` (lines ~99–105, `__all__` ~125)
- Modify: `apps/api/src/yupay/modules/merchants/machine_routes.py` (`validate_player`, ~lines 247–275)
- Modify: `apps/api/src/yupay/modules/merchants/quote.py` — no code change; `unavailable(identifier, reason)` is reused with reason `unknown_brand`
- Test: `apps/api/tests/integration/test_merchant_validate.py`
- Docs: `docs/api/README.md` (§`POST /merchant/v1/validate/player`), `docs/runbooks/merchant-b2b.md` (§keeps answering `error`), regenerate `docs/api/merchant-openapi.json` + `docs/api/openapi.json` via `make gen-api`

**Interfaces:**

- Consumes: `brand_check_field`, `check_player_for_brand_id` (Task 2).
- Produces: request body `{brand: str, player_id: str, server_id?: str}`; facade export `check_player_for_brand` (replacing `check_player_for_sku`); refusals `404 item_unavailable` with `reason` ∈ `unknown_brand | not_b2b_visible`.

- [ ] **Step 1: Rewrite the merchant tests first**

In `test_merchant_validate.py`: every `_validate(integration_client, credentials, {"sku_id": g2b_sku_id, ...})` becomes `{"brand": "brand-validate-1", ...}` (the `_tree(1, ...)` brand slug behind `g2b_sku_id`; keep the fixture — it still seeds the brand and its mapping). Replace the "unknown sku" / "withheld sku" tests with:

```python
async def test_a_sku_id_is_no_longer_accepted(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The body is a brand now. `extra="forbid"` turns the old field into a
    422 that names it, instead of a check of nothing."""
    r = await _validate(
        integration_client, credentials, {"sku_id": g2b_sku_id, "player_id": "51234567"}
    )
    assert r.status_code == 422, r.text
    assert "brand" in r.text


async def test_an_unknown_brand_is_refused_by_name(
    integration_client: AsyncClient, credentials: tuple[str, str]
) -> None:
    r = await _validate(
        integration_client, credentials, {"brand": "no-such-brand", "player_id": "1"}
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == "item_unavailable"
    assert body["reason"] == "unknown_brand"


async def test_a_brand_withheld_from_b2b_is_not_checkable(
    integration_client: AsyncClient, credentials: tuple[str, str], db_session: AsyncSession
) -> None:
    category, brand, product, sku = _tree(7, required_fields=_G2B_FIELD, brand_visible_b2b=False)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    r = await _validate(
        integration_client, credentials, {"brand": brand.slug, "player_id": "1"}
    )
    assert r.status_code == 404, r.text
    assert r.json()["reason"] == "not_b2b_visible"
```

The existing fan-out test (`test_the_check_does_not_fan_out_over_the_catalog`, ~line 687) asserts `spent <= 6` and its body sends `sku_id`; change the body to `{"brand": "brand-validate-1", ...}` and leave the bound at 6. The new path costs 5 statements before the supplier call (brand, one visible SKU, products' `required_fields` twice — once in `validate.py`, once in `check_player_for_brand_id` — and mappings). If the test fails, the implementation loaded an entity somewhere (`Brand.products` fans out); fix the query, never the bound.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest apps/api/tests/integration/test_merchant_validate.py -q`
Expected: FAIL — 422 on `brand` (unknown field) for the happy-path tests.

- [ ] **Step 3: Implement**

`machine_schemas.py` — replace the `sku_id` field of `MerchantPlayerCheckIn` with:

```python
    brand: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description=(
            "The brand you are about to order from, by its slug as listed in "
            "`GET /merchant/v1/catalog`. A brand and not a SKU, because a brand is one "
            "game (ADR-0079): the id you check here is the id every SKU of the brand "
            "credits."
        ),
    )
```

and update the class docstring's last sentence to "…gets read as \"this brand needs no verification\"."

`validate.py` — replace `_checkable_product` with:

```python
async def _checkable_brand(db: AsyncSession, *, brand_slug: str) -> str:
    """Resolve a merchant-visible brand slug to its id.

    The rule is ``/catalog``'s: the brand is ``visible_b2b`` and at least one of
    its SKUs is. A brand withheld from B2B is not checkable, so this endpoint
    cannot be used to enumerate what ``/catalog`` hides.

    Raises:
        NotFoundError: ``item_unavailable`` with ``reason`` — ``unknown_brand``
            for a slug that names nothing, ``not_b2b_visible`` for one the
            merchant cannot see.
    """
    row = (
        await db.execute(
            select(Brand.id, Brand.visible_b2b).where(
                Brand.slug == brand_slug, Brand.active.is_(True)
            )
        )
    ).one_or_none()
    if row is None:
        raise quote.unavailable(brand_slug, "unknown_brand")
    brand_id, visible = row
    if not visible:
        raise quote.unavailable(brand_slug, "not_b2b_visible")
    any_visible_sku = (
        await db.execute(
            select(Sku.id)
            .join(Product, Product.id == Sku.product_id)
            .where(Product.brand_id == brand_id, Sku.visible_b2b.is_(True), Sku.active.is_(True))
            .limit(1)
        )
    ).first()
    if any_visible_sku is None:
        raise quote.unavailable(brand_slug, "not_b2b_visible")
    return brand_id
```

and `check_player` with:

```python
async def check_player(
    db: AsyncSession, *, brand: str, player_id: str, server_id: str | None
) -> MerchantPlayerCheckOut:
    """Advisory player check for a reseller, scoped to a brand they can see.

    Returns ``unsupported`` when no product of the brand declares a check — the
    reseller orders without one — and otherwise the provider's own verdict
    (``valid`` / ``invalid``) or ``error`` when we could not check.
    """
    brand_id = await _checkable_brand(db, brand_slug=brand)
    if await player_check.brand_check_field(db, brand_id) is None:
        return MerchantPlayerCheckOut(status=STATUS_UNSUPPORTED)
    result = await player_check.check_player_for_brand_id(
        db, brand_id=brand_id, player_id=player_id, server_id=server_id
    )
    return MerchantPlayerCheckOut(status=result.status, name=result.name)
```

(Imports: `Brand`, `Product`, `Sku` from `yupay.modules.catalog.models`; drop the now-unused ones. `brand_check_field` runs twice — once here, once inside `check_player_for_brand_id` — on a two-column query; keep it simple.)

`api.py` — rename the facade export: `check_player as check_player_for_brand` and `__all__` entry `"check_player_for_brand"`.

`machine_routes.py` — in `validate_player`, replace the dispatch with:

```python
    return await merchants.check_player_for_brand(
        db, brand=body.brand, player_id=body.player_id, server_id=body.server_id
    )
```

and in its docstring replace "against the SKU you intend to buy" with "for the brand you intend to buy from — a brand is one game (ADR-0079), so the id you check is the id every SKU of it credits", and "this SKU has no checker" with "this brand has no checker".

- [ ] **Step 4: Run the merchant tests and the type check**

Run: `uv run pytest apps/api/tests/integration/test_merchant_validate.py apps/api/tests/integration/test_player_check_endpoint.py -q && uv run ruff check apps/api && uv run mypy apps/api/src`
Expected: all pass, clean. Fix the fan-out count per Step 1's rule.

- [ ] **Step 5: Docs and the published contract**

- `docs/api/README.md`, section `### POST /merchant/v1/validate/player — the truthful player check`: replace "`merchants/validate.py` resolves the SKU and projects the result" with "`merchants/validate.py` resolves the **brand** and projects the result"; replace the paragraph starting "**Scoped to what the merchant can already see**" so it reads: brand `visible_b2b` **and** at least one B2B-visible SKU, refusals `404 item_unavailable` with `reason: unknown_brand` or `not_b2b_visible`; add one sentence: "The body takes a brand, not a SKU: a brand is exactly one game (ADR-0079), so the id checked is the id every SKU of the brand credits — and it is how every other reseller API in this market is shaped."
- `docs/runbooks/merchant-b2b.md`, §"keeps answering `error`", cause 1: "The product has no active supplier mapping" → "The **brand** has no active supplier mapping … logs `player_check_no_game_mapping` with the `brand_id`"; add cause 1b: "The brand spans two G2B games (`player_check_brand_spans_games`) — the catalog is mid-split; finish the split (ADR-0079)."
- Run `make gen-api`; confirm `git diff --stat docs/api/merchant-openapi.json` shows the `MerchantPlayerCheckIn` change.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/merchants apps/api/tests/integration/test_merchant_validate.py docs/api packages/api-client docs/runbooks/merchant-b2b.md
git commit -m "feat(merchants): validate/player takes a brand, not a sku_id

A brand is one game (ADR-0079), and every reseller API in this market takes a
brand. Zero live traffic carried sku_id, so the field is removed rather than
dual-moded; extra=\"forbid\" turns it into a 422 that names the new field."
```

---

### Task 5: Storefront — check before a package is picked, verdicts keyed by brand

**Files:**

- Modify: `apps/web/src/lib/player-check.ts`
- Modify: `apps/web/src/lib/player-check-state.ts`
- Modify: `apps/web/src/components/store/PurchasePanel.tsx` (`CheckablePlayerField` props ~168–245, the `t("checkNeedsSku")` branch ~422, `currentFieldCheck` ~1116–1128, the call site ~1838–1868)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` — remove `store.checkNeedsSku`
- Test: `apps/web/src/lib/player-check-state.test.ts` (if present; else create), `apps/web/src/components/store/PurchasePanel.test.tsx` (tests at ~570–700)

**Interfaces:**

- Consumes: `POST /catalog/brands/{slug}/check-player` (Task 3).
- Produces:
  - `checkPlayer(brandSlug: string, input: {playerId; serverId?}) => Promise<PlayerCheckResult>`
  - `runPlayerCheck(brandSlug, input, run?)`
  - `PlayerCheckVerdict { brandSlug: string; playerId: string; serverId: string | null; result }`
  - `currentCheck(verdict, brandSlug, playerId, serverId)`
  - `CheckBlocker = "playerId" | "serverId"`; `checkBlocker({ value, pattern?, server? })` — no `productChosen`.
  - `CheckablePlayerField` prop `brandSlug: string` (replaces `productId`), no `productChosen`.

- [ ] **Step 1: Rewrite the two gate tests first**

In `PurchasePanel.test.tsx` replace `it("will not check a region-split brand until a package is picked", …)` with:

```ts
it("checks before a package is picked, however many products the brand sells", async () => {
  // A brand is one game now (ADR-0079), so there is nothing a package choice
  // could change about which account is checked. The old gate cost PUBG's
  // five-product page a click for a distinction that only ever applied to
  // MLBB — which is two brands today.
  mockProvidersResponse(ALL_PROVIDERS_ACTIVE);
  const base = makeProduct();
  const uc: ProductDetail = { ...base, required_fields: MLBB_FIELDS };
  const pass: ProductDetail = {
    ...uc,
    id: "prod-2",
    slug: "pubg-royal-pass",
    skus: [{ ...base.skus[0]!, id: "sku-2", sku_code: "PUBG-RP" }],
  };
  renderPanel(<PurchasePanel products={[uc, pass]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });
  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  expect(screen.getByRole("button", { name: "check" })).toHaveAttribute("aria-disabled", "false");
  expect(screen.queryByText("checkNeedsSku")).not.toBeInTheDocument();
});
```

Keep `it("checks straight away on a single-product brand", …)` as is. Add, after it:

```ts
it("keeps the verdict when the customer switches package inside the brand", async () => {
  // The verdict answers for the brand's game, and every package of the brand
  // is that game — invalidating it on a package switch made the customer
  // re-check the same id for nothing.
  mockProvidersResponse(ALL_PROVIDERS_ACTIVE);
  vi.spyOn(playerCheck, "checkPlayer").mockResolvedValue({ status: "valid", name: "Neo" });
  const base = makeProduct();
  const a: ProductDetail = {
    ...base,
    required_fields: MLBB_FIELDS,
    skus: [
      { ...base.skus[0]!, id: "sku-a", sku_code: "A-1" },
      { ...base.skus[0]!, id: "sku-b", sku_code: "A-2" },
    ],
  };
  renderPanel(<PurchasePanel products={[a]} locale="ru" />);
  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  fireEvent.click(screen.getByRole("button", { name: "check" }));
  expect(await screen.findByText(/Neo/)).toBeInTheDocument();

  fireEvent.click(screen.getByText("A-2"));
  expect(screen.getByText(/Neo/)).toBeInTheDocument();
});
```

(`import * as playerCheck from "@/lib/player-check";` at the top of the test file; `MLBB_FIELDS` already exists in the file — reuse it. If a package tile is not selected by its `sku_code` text in this file's other tests, use whatever selector `it("makes the typed amount and a package mutually exclusive")` uses.)

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --filter @yupay/web exec vitest run src/components/store/PurchasePanel.test.tsx -t "before a package|switches package"`
Expected: FAIL — the check button is `aria-disabled="true"` / `checkNeedsSku` rendered.

- [ ] **Step 3: Implement the lib changes**

`player-check.ts`:

```ts
export function checkPlayer(
  brandSlug: string,
  input: { playerId: string; serverId?: string | null },
): Promise<PlayerCheckResult> {
  return apiFetch<PlayerCheckResult>(
    `/catalog/brands/${encodeURIComponent(brandSlug)}/check-player`,
    {
      method: "POST",
      body: { player_id: input.playerId, server_id: input.serverId ?? null },
      anonymous: true,
    },
  );
}
```

`player-check-state.ts` — replace the corresponding definitions with:

```ts
export type CheckBlocker = "playerId" | "serverId";

export function checkBlocker(input: {
  value: string;
  pattern?: string | null | undefined;
  server?: { required: boolean; id: string | null | undefined } | null | undefined;
}): CheckBlocker | null {
  const v = input.value.trim();
  if (v.length === 0) return "playerId";
  if (input.pattern) {
    // keep the existing pattern branch exactly as it is today
  }
  // keep the existing server branch exactly as it is today
  return null;
}

export async function runPlayerCheck(
  brandSlug: string,
  input: { playerId: string; serverId?: string | null },
  run: typeof checkPlayer = checkPlayer,
): Promise<PlayerCheckResult> {
  try {
    return await run(brandSlug, input);
  } catch {
    return { status: "error", name: null };
  }
}

export interface PlayerCheckVerdict {
  /** The brand the lookup was scoped to — one game, so one verdict per brand. */
  brandSlug: string;
  playerId: string;
  serverId: string | null;
  result: PlayerCheckResult;
}

export function currentCheck(
  verdict: PlayerCheckVerdict | null | undefined,
  brandSlug: string,
  playerId: string,
  serverId: string | null,
): PlayerCheckResult | null {
  if (verdict == null) return null;
  return verdict.brandSlug === brandSlug &&
    verdict.playerId === playerId &&
    verdict.serverId === serverId
    ? verdict.result
    : null;
}
```

Only the `productChosen` lines are removed from `checkBlocker`; its pattern and server branches stay byte-for-byte.

`PurchasePanel.tsx` lines 144–151 hold the in-flight question helper; replace them with:

```ts
interface Question {
  brandSlug: string;
  playerId: string;
  serverId: string | null;
}

function sameQuestion(a: Question, b: Question): boolean {
  return a.brandSlug === b.brandSlug && a.playerId === b.playerId && a.serverId === b.serverId;
}
```

and at its three uses (~lines 220, 260, 266) replace `productId` with `brandSlug`. `rg -n "productId" apps/web/src/lib/player-check-state.ts apps/web/src/components/store/PurchasePanel.tsx` must come back empty when you are done.

`PurchasePanel.tsx`:

- `CheckablePlayerField`: prop `productId: string` → `brandSlug: string`; delete the `productChosen` prop, its destructuring, the `productChosen` argument to `checkBlocker`, and the `blocker === "product" ? t("checkNeedsSku") : …` branch (~line 422).
- `currentFieldCheck`: `fieldsProduct?.id ?? ""` → `fieldsProduct?.brand.slug ?? ""`.
- Call site: `productId={fieldsProduct.id}` → `brandSlug={fieldsProduct.brand.slug}`; delete the `productChosen={…}` line and its comment block (the six lines explaining the ADR-0048 gate). Delete the ADR-0048 comment on `currentFieldCheck` ("the package now points at another product…") — replace with: `// Keyed by brand: every package of a brand is the same game (ADR-0079), so a verdict survives a package switch and dies only with the id or the server.`
- i18n: remove `store.checkNeedsSku` from `ru`, `en`, `uz` `web.json`.

- [ ] **Step 4: Run the web suite and the checks**

Run: `pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/web exec vitest run src/components/store src/lib && pnpm --filter @yupay/web exec eslint src/lib/player-check.ts src/lib/player-check-state.ts src/components/store/PurchasePanel.tsx`
Expected: tsc clean (any leftover `productChosen`/`productId` reference fails here — fix it), all tests pass, no eslint errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/player-check.ts apps/web/src/lib/player-check-state.ts apps/web/src/components/store/PurchasePanel.tsx apps/web/src/components/store/PurchasePanel.test.tsx packages/i18n/locales
git commit -m "feat(web/store): check the player id before a package is picked, keyed by brand"
```

---

### Task 6: Storefront — the sibling-region link and the "try the other region" hint

**Files:**

- Create: `apps/web/src/lib/region-sibling.ts`, `apps/web/src/lib/region-sibling.test.ts`
- Modify: `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx` (data load ~100–118; insert the notice just above `<div className="mt-8">` ~line 410)
- Modify: `apps/web/src/components/store/PurchasePanel.tsx` (new optional prop `regionSibling`, passed into `CheckablePlayerField` as `siblingHint`; rendered under the `invalid` message)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` — add `store.regionSiblingRu`, `store.regionSiblingGlobal`, `store.checkTryRegion`

**Interfaces:**

- Consumes: `getBrands(locale)` → `BrandSummary[]` (`@/lib/catalog`).
- Produces: `regionSibling(slug: string, brands: BrandSummary[]): BrandSummary | null`; `PurchasePanel` prop `regionSibling?: { slug: string; name: string } | null`.

- [ ] **Step 1: Write the failing unit test**

`apps/web/src/lib/region-sibling.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { regionSibling } from "./region-sibling";

import type { BrandSummary } from "./catalog";

function brand(slug: string): BrandSummary {
  return {
    id: slug,
    slug,
    category_slug: "games",
    name: slug,
    short_description: null,
    logo_url: null,
    hero_image_url: null,
    accent_color: null,
    maintenance: false,
  };
}

describe("regionSibling", () => {
  const brands = [brand("mobile-legends"), brand("mobile-legends-ru"), brand("pubg-mobile")];

  it("pairs a global brand with its -ru twin", () => {
    expect(regionSibling("mobile-legends", brands)?.slug).toBe("mobile-legends-ru");
  });
  it("pairs a -ru brand with its global twin", () => {
    expect(regionSibling("mobile-legends-ru", brands)?.slug).toBe("mobile-legends");
  });
  it("is null for a brand with no twin", () => {
    expect(regionSibling("pubg-mobile", brands)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/region-sibling.test.ts`
Expected: FAIL — cannot resolve `./region-sibling`.

- [ ] **Step 3: Implement the helper**

`apps/web/src/lib/region-sibling.ts`:

```ts
import type { BrandSummary } from "./catalog";

/**
 * The other region's brand, for the two games we sell as two brands.
 *
 * A brand is one supplier game (ADR-0079), so Mobile Legends and Mobile
 * Legends RU are separate brands. The pairing is the slug convention
 * `<slug>` ↔ `<slug>-ru` rather than a column: two brands do not justify a
 * schema, and the convention is the one the seed that created them follows.
 */
export function regionSibling(slug: string, brands: BrandSummary[]): BrandSummary | null {
  const twin = slug.endsWith("-ru") ? slug.slice(0, -"-ru".length) : `${slug}-ru`;
  return brands.find((b) => b.slug === twin) ?? null;
}
```

- [ ] **Step 4: Run the unit test**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/region-sibling.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire it into the brand page and the panel**

i18n, `store` namespace (all three files):

```json
"regionSiblingRu": "Аккаунт российского региона? Вам на страницу {name}",
"regionSiblingGlobal": "Аккаунт глобального региона? Вам на страницу {name}",
"checkTryRegion": "Если аккаунт другого региона — проверьте на странице {name}"
```

en: `"Russian-region account? Use the {name} page"`, `"Global-region account? Use the {name} page"`, `"If the account is in the other region, check it on the {name} page"`.
uz: `"Rossiya mintaqasi akkauntimi? Sizga {name} sahifasi"`, `"Global mintaqa akkauntimi? Sizga {name} sahifasi"`, `"Agar akkaunt boshqa mintaqada boʻlsa — {name} sahifasida tekshiring"`.

`[brandSlug]/page.tsx`: next to the existing loads add

```tsx
import { getBrands } from "@/lib/catalog";
import { regionSibling } from "@/lib/region-sibling";
// …
const sibling = regionSibling(brand.slug, await getBrands(locale));
```

and immediately above `<div className="mt-8">` render:

```tsx
{
  sibling && (
    <p className="border-border/70 mt-6 rounded-md border border-dashed px-4 py-3 text-[14px]">
      <Link
        href={pathFor(locale, `/store/${sibling.slug}`)}
        className="text-primary font-semibold hover:underline"
      >
        {t(brand.slug.endsWith("-ru") ? "regionSiblingGlobal" : "regionSiblingRu", {
          name: sibling.name,
        })}
      </Link>
    </p>
  );
}
```

and pass `regionSibling={sibling ? { slug: sibling.slug, name: sibling.name } : null}` into `<PurchasePanel …>`.

`PurchasePanel.tsx`: add `regionSibling?: { slug: string; name: string } | null` to its props; pass `siblingHint={regionSibling ?? null}` to `CheckablePlayerField`; in the field, where the `invalid` message (`t("checkNotFound")`) renders, add directly under it:

```tsx
{
  siblingHint && (
    <a
      href={`/store/${siblingHint.slug}`}
      className="text-primary text-[13px] underline-offset-4 hover:underline"
    >
      {t("checkTryRegion", { name: siblingHint.name })}
    </a>
  );
}
```

(`CheckablePlayerField` receives `t` already; the `href` uses the locale-less path because the field has no `locale` prop — use `pathFor` only if the panel already passes `locale` down; it does (`locale` prop on the panel) — prefer `pathFor(locale, …)` and thread `locale` through if it is one prop away.)

- [ ] **Step 6: Add the panel test and run everything**

Append to `PurchasePanel.test.tsx`:

```ts
it("points a not-found id at the other region when the brand has one", async () => {
  mockProvidersResponse(ALL_PROVIDERS_ACTIVE);
  vi.spyOn(playerCheck, "checkPlayer").mockResolvedValue({ status: "invalid", name: null });
  renderPanel(
    <PurchasePanel
      products={[{ ...makeProduct(), required_fields: MLBB_FIELDS }]}
      locale="ru"
      regionSibling={{ slug: "mobile-legends-ru", name: "Mobile Legends RU" }}
    />,
  );
  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  fireEvent.click(screen.getByRole("button", { name: "check" }));
  expect(await screen.findByText("checkNotFound")).toBeInTheDocument();
  expect(screen.getByText("checkTryRegion")).toHaveAttribute("href", expect.stringContaining("/store/mobile-legends-ru"));
});
```

Run: `pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/web exec vitest run && pnpm --filter @yupay/web exec eslint src && pnpm exec prettier --check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/lib/region-sibling.ts apps/web/src/lib/region-sibling.test.ts "apps/web/src/app/[locale]/store/[brandSlug]/page.tsx" apps/web/src/components/store/PurchasePanel.tsx apps/web/src/components/store/PurchasePanel.test.tsx packages/i18n/locales
git commit -m "feat(web/store): link the sibling region brand, and point a not-found id at it"
```

---

### Task 7: ADR-0079 and the last docs

**Files:**

- Create: `docs/decisions/0079-region-brands-and-brand-level-player-check.md`
- Modify: `docs/decisions/0048-mobile-legends-region-split.md`: set `Status: Superseded by 0079`
- Modify: `docs/decisions/0031-storefront-player-check.md`: add an amendment naming the brand endpoint

- [ ] **Step 1: Write the ADR**

```markdown
# 0079. Region brands, and a player check bound to the brand

- **Status**: Accepted
- **Date**: 2026-09-16
- **Deciders**: owner, Claude
- **Tags**: backend | frontend | data
- **Supersedes**: [ADR-0048](./0048-mobile-legends-region-split.md)

## Context and problem statement

The player-id check was bound to a product, because Mobile Legends (and Magic
Chess: Go Go) sold two regions — two supplier games — as two products of one
brand (ADR-0048). Consequences: the storefront could not check an id before a
package was picked on any brand with more than one product (ten brands, eight
of which are one game); the reseller API took a `sku_id` where every
competitor takes a brand; and "which unit is one game" was answered
differently by customers (the brand), the catalog (the product) and G2B (the
game code).

## Decision drivers

- One mental model: a brand is one game.
- The check must never guess (ADR-0031): two games behind one brand → no check.
- Customers know their region (owner, from support); the split moves the
  choice to the catalog, where names carry it.
- `POST /merchant/v1/validate/player` had zero traffic in 14 days.

## Considered options

1. **Split MLBB and MCGG into global + RU brands; bind the check to the brand.**
2. Keep one brand; bind the check to brand + region — not an option without a
   region, which is a product choice by another name.
3. Keep the catalog; probe every game behind a brand and report which matched.
   Better for a customer who does not know their region; more code and two
   supplier calls per check. Set aside because customers do know.

## Decision outcome

Option 1. `mobile-legends-ru` and `magic-chess-gogo-ru` exist; the global
slugs are unchanged. `resolve_g2b_game_code` is brand-scoped and refuses on
two codes (`player_check_brand_spans_games`). Public
`POST /catalog/brands/{slug}/check-player` replaces the product route;
`validate/player` takes `brand`. The storefront checks before a package is
picked and keys verdicts by brand; the two split brands link to each other
and point a not-found id at the sibling.

Rollout: seed first, code second — the product-scoped check did not read the
brand, so the data split was safe on the old release, while the new resolver
on the old data would have refused MLBB.

## Consequences

- Reviews stay with the global brands; the RU brands start at zero.
- Merchant Center feed titles of RU SKUs change (offerId is `sku_code`, so
  nothing is deleted).
- A future two-game brand fails loudly (`error` + log) instead of quietly
  checking the wrong game.

## References

- Spec: `docs/superpowers/specs/2026-09-16-brand-level-player-check-design.md`
- ADR-0031, ADR-0048
```

- [ ] **Step 2: Mark 0048 superseded, amend 0031**

In `0048-mobile-legends-region-split.md` change the status line to `- **Status**: Superseded by [0079](./0079-region-brands-and-brand-level-player-check.md)`. In `0031-storefront-player-check.md` append:

```markdown
## Amendment — 2026-09-16: the check is per brand

`POST /catalog/products/{id}/check-player` is gone; the storefront and the
reseller API both check per **brand** (`POST /catalog/brands/{slug}/check-player`,
`validate/player {brand}`), because a brand is one supplier game — ADR-0079
carries the reasoning and the MLBB/MCGG split that made it true.
```

- [ ] **Step 3: Full check and commit**

Run: `make lint typecheck test && pnpm exec prettier --check .`
Expected: all green.

```bash
git add docs/decisions
git commit -m "docs(adr): 0079 region brands and the brand-level player check; supersede 0048"
```

---

## Rollout (operator, after the plan is merged — needs the owner's explicit go)

1. **Seed on prod, before deploying.** From the repo root, with the prod checkout on the commit that carries the seed:
   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@152.228.137.175 'cd /home/ubuntu/opt/yupay && docker compose -f docker-compose.prod.yml exec -T postgres psql -U yupay_app -d yupay -v ON_ERROR_STOP=1' < scripts/seed/2026-09-16_region_brands.sql
   ```
   Then: `curl -s -o /dev/null -w "%{http_code}\n" https://yupay.uz/store/mobile-legends-ru` → 200 within 5 min (ISR), same for `magic-chess-gogo-ru`; `GET https://api.yupay.uz/api/v1/catalog/brands` lists four; the old pages still check per product (old code).
2. **Deploy** (push → Build images → `deploy.yml` production).
3. **Verify:** `POST https://api.yupay.uz/api/v1/catalog/brands/pubg-mobile/check-player` with `{"player_id":"1"}` → 200 with `status` ∈ valid/invalid/error; the product route → 404; on `/store/pubg-mobile` the check button is enabled before a package is picked; on `/store/mobile-legends` the RU link renders and vice versa; a signed `validate/player {brand: "mobile-legends"}` answers 200 (use the merchant test's signing helper against prod credentials, or the Swagger UI).
4. **Watch** the api logs for `player_check_brand_spans_games` for a day: any hit means a brand still spans two games.
