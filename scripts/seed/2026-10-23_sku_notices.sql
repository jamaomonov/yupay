-- Notices on packs that do not give everyone what their name suggests, and MLBB
-- packs named by what the game gives.
--
-- Why: MLBB's «First Top-Up» packs (50 + 5, 150 + 15, 250 + 25, 500 + 65 and the
-- double 50 + 50 … 500 + 500) add their bonus once per account. We sold the global
-- one as «275 Diamonds»; a buyer who had the bonus before got 250 (2026-10-23,
-- order 01a1681a). Regular packs (234 + 23 …) give the bonus every time, but the
-- global names hid the split, and game events count the base alone. Free Fire's
-- Level Up packages work only below their level, and Weekly Membership arrives
-- over seven days (owner's copy, 2026-10-23).
--
-- What it does:
--   1. skus.notice (migration 0106) — a tile label and a line before paying:
--      a. one-off bonus: the MLBB «(First Top-Up )» regions, and the G2B global/BR/US
--         55 / 165 / 275 / 565 (G2B names them bare; they are the same packs);
--      b. once per account: packs other games sell once (Rainbow Six «FIRST PURCHASE
--         ONLY», PUBG «First Purchase Pack», Eggy Party, Revelation);
--      c. Free Fire Level Up packages, every region, with their level;
--      d. Free Fire Weekly Membership: the CIS one with its numbers (150 + 6 × 50),
--         the other regions without — their split is not confirmed.
--   2. MLBB first-top-up names become «250 + 25 Diamonds» — base first.
--   3. MLBB global regular packs show the split: «257 Diamonds (234 + 23)», as the
--      regional ones already do. Only packs whose split a supplier names.
--
-- Idempotent: a re-run writes the same values. Needs migration 0106. Apply on prod
-- (operator psql), after the deploy:
--   docker compose -p yupay-prod exec -T postgres \
--     psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 -f - < scripts/seed/2026-10-23_sku_notices.sql

BEGIN;

-- 1a. One-off bonus.
UPDATE skus SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '1-я покупка', 'en', 'First purchase', 'uz', 'Birinchi xarid'),
  'text', jsonb_build_object(
    'ru', 'Бонус — только при первой покупке этого пакета в игре. Если брали его раньше, придёт без бонуса.',
    'en', 'The bonus comes only with the first purchase of this pack in the game. Bought it before? It arrives without the bonus.',
    'uz', 'Bonus faqat ushbu paketni oʻyinda birinchi marta olganda beriladi. Avval olgan boʻlsangiz, bonussiz keladi.'))
WHERE denomination ~* '\(First Top-Up'
   OR sku_code IN (
     'mlbb-55', 'mlbb-165', 'mlbb-275', 'mlbb-565',
     'mobile-legends-br-55', 'mobile-legends-br-165',
     'mobile-legends-br-275', 'mobile-legends-br-565',
     'mobile-legends-us-55'
   );

-- 1b. Sold once per account.
UPDATE skus SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '1 раз на аккаунт', 'en', 'Once per account', 'uz', 'Akkauntga 1 marta'),
  'text', jsonb_build_object(
    'ru', 'Игра продаёт этот пакет один раз на аккаунт. Если вы его уже брали, заказ не выполнится.',
    'en', 'The game sells this pack once per account. If you have bought it before, the order will not go through.',
    'uz', 'Oʻyin bu paketni akkauntga bir marta sotadi. Avval olgan boʻlsangiz, buyurtma bajarilmaydi.'))
WHERE denomination ~* 'first purchase|first pay package';

-- 1c. Free Fire Level Up, with the level from the name («Level Up Package 30»,
--     «Level Up Package - Level 30», «Level Up Pass - Level 30»).
UPDATE skus AS s SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', 'До ' || l.lvl || ' уровня', 'en', 'Up to level ' || l.lvl, 'uz', l.lvl || '-levelgacha'),
  'text', jsonb_build_object(
    'ru', 'Сработает, если уровень аккаунта не выше ' || l.lvl || ' и этот Level Up ещё не получен. Проверьте в игре, в разделе Level Up Pass.',
    'en', 'Works only if the account is at level ' || l.lvl || ' or below and this Level Up is not claimed yet. Check under Level Up Pass in the game.',
    'uz', 'Akkaunt darajasi ' || l.lvl || ' dan oshmagan va bu Level Up hali olinmagan boʻlsa ishlaydi. Oʻyinda Level Up Pass boʻlimida tekshiring.'))
FROM (
  SELECT s2.id, substring(s2.denomination from '(\d+)\s*$') AS lvl
  FROM skus s2 JOIN products p ON p.id = s2.product_id JOIN brands b ON b.id = p.brand_id
  WHERE b.slug LIKE 'free-fire%' AND s2.denomination ~* '^Level Up (Package|Pass).*\d+\s*$'
) AS l
WHERE s.id = l.id;

-- The Taiwan pass names no level.
UPDATE skus AS s SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', 'Проверьте уровень', 'en', 'Check your level', 'uz', 'Levelni tekshiring'),
  'text', jsonb_build_object(
    'ru', 'Сработает, если этот Level Up ещё не получен и уровень аккаунта не выше нужного. Проверьте в игре, в разделе Level Up Pass.',
    'en', 'Works only if this Level Up is not claimed yet and the account is not above its level. Check under Level Up Pass in the game.',
    'uz', 'Bu Level Up hali olinmagan va akkaunt darajasi undan oshmagan boʻlsa ishlaydi. Oʻyinda Level Up Pass boʻlimida tekshiring.'))
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE s.product_id = p.id AND b.slug LIKE 'free-fire%' AND s.denomination ~* '^Level Up Pass$';

-- 1d. Free Fire Weekly Membership: CIS with its numbers, the rest without.
UPDATE skus SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '7 дней', 'en', '7 days', 'uz', '7 kun'),
  'text', jsonb_build_object(
    'ru', '450 алмазов за 7 дней: 150 в день покупки, затем по 50 каждый день.',
    'en', '450 diamonds over 7 days: 150 on the day you buy, then 50 a day.',
    'uz', '7 kunda 450 olmos: xarid kuni 150, keyin har kuni 50 tadan.'))
WHERE sku_code = 'freefire_cis-weekly-membership';

UPDATE skus AS s SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '7 дней', 'en', '7 days', 'uz', '7 kun'),
  'text', jsonb_build_object(
    'ru', 'Алмазы приходят не сразу, а частями каждый день в течение 7 дней.',
    'en', 'The diamonds arrive in daily parts over 7 days, not at once.',
    'uz', 'Olmoslar birdaniga emas, 7 kun davomida har kuni qismlab keladi.'))
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE s.product_id = p.id AND b.slug LIKE 'free-fire%'
  AND s.denomination ~* '^Weekly( Membership)?$'
  AND s.sku_code <> 'freefire_cis-weekly-membership';

-- 2. First-top-up names: «275 Diamonds (First Top-Up ) (250 + 25)» → «250 + 25 Diamonds».
UPDATE skus
SET denomination = regexp_replace(
      denomination, '^\d+ Diamonds \(First Top-Up \) \((\d+) \+ (\d+)\)$', '\1 + \2 Diamonds'),
    updated_at = now()
WHERE denomination ~ '^\d+ Diamonds \(First Top-Up \) \(\d+ \+ \d+\)$';

UPDATE skus AS s SET denomination = v.name, updated_at = now()
FROM (VALUES
  ('mlbb-55', '50 + 5 Diamonds'),
  ('mlbb-165', '150 + 15 Diamonds'),
  ('mlbb-275', '250 + 25 Diamonds'),
  ('mlbb-565', '500 + 65 Diamonds'),
  ('mobile-legends-br-55', '50 + 5 Diamonds'),
  ('mobile-legends-br-165', '150 + 15 Diamonds'),
  ('mobile-legends-br-275', '250 + 25 Diamonds'),
  ('mobile-legends-br-565', '500 + 65 Diamonds'),
  ('mobile-legends-us-55', '50 + 5 Diamonds'),
  -- 3. Global regular packs: the total, then the split.
  ('mlbb-86', '86 Diamonds (78 + 8)'),
  ('mlbb-172', '172 Diamonds (156 + 16)'),
  ('mlbb-257', '257 Diamonds (234 + 23)'),
  ('mlbb-344', '344 Diamonds (310 + 34)'),
  ('mlbb-706', '706 Diamonds (625 + 81)'),
  ('mlbb-2195', '2195 Diamonds (1860 + 335)'),
  ('mlbb-3688', '3688 Diamonds (3099 + 589)')
) AS v(code, name)
WHERE s.sku_code = v.code AND s.denomination IS DISTINCT FROM v.name;

-- What it left: every SKU with a notice, its name and label.
SELECT sku_code, denomination, notice -> 'badge' ->> 'ru' AS badge
FROM skus WHERE notice IS NOT NULL ORDER BY sku_code;

COMMIT;
