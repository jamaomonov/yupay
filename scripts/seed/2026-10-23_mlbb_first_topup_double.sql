-- MLBB first-top-up notice, corrected: the first purchase of a tier doubles it.
--
-- 2026-10-23_sku_notices.sql said «the bonus comes only with the first purchase»,
-- which reads as if a repeat buyer gets the bare base. The game works the other
-- way (owner, confirmed against reseller guides): the first purchase of each tier
-- (50 / 150 / 250 / 500) doubles it — 250 + 250 — and every later one gives the
-- regular bonus — 250 + 25. So the pack named «250 + 25 Diamonds» is the floor, and
-- a first-time buyer gets more. The ID region's «50 + 50» packs are named by the
-- doubled value; there a repeat buyer gets less than the name, so their text says so.
--
-- Touches only SKUs that carry the «1-я покупка» notice. Idempotent. Apply on prod
-- (operator psql):
--   docker compose -p yupay-prod exec -T postgres \
--     psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 -f - < scripts/seed/2026-10-23_mlbb_first_topup_double.sql

BEGIN;

-- «250 + 25 Diamonds»: the floor; ×2 on the first purchase of the tier.
UPDATE skus AS s SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '×2 в первый раз', 'en', '×2 first time', 'uz', '1-marta ×2'),
  'text', jsonb_build_object(
    'ru', 'Если вы ещё не покупали этот номинал в игре, алмазы удвоятся: придёт ' || n.b || ' + ' || n.b || '. Иначе — ' || n.b || ' + ' || n.x || '.',
    'en', 'If you have never bought this tier in the game, the diamonds double: ' || n.b || ' + ' || n.b || '. Otherwise you get ' || n.b || ' + ' || n.x || '.',
    'uz', 'Bu nominalni oʻyinda hali olmagan boʻlsangiz, olmoslar ikki baravar boʻladi: ' || n.b || ' + ' || n.b || '. Aks holda ' || n.b || ' + ' || n.x || ' keladi.'))
FROM (
  SELECT id,
         substring(denomination from '^(\d+) \+') AS b,
         substring(denomination from '\+ (\d+) Diamonds$') AS x
  FROM skus
  WHERE notice -> 'badge' ->> 'ru' IN ('1-я покупка', '×2 в первый раз')
    AND denomination ~ '^\d+ \+ \d+ Diamonds$'
) AS n
WHERE s.id = n.id AND n.b <> n.x;

-- «50 + 50 Diamonds» (ID): named by the doubled value, so a repeat buyer gets less.
UPDATE skus SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', '1-я покупка', 'en', 'First purchase', 'uz', 'Birinchi xarid'),
  'text', jsonb_build_object(
    'ru', 'Удвоение — только при первой покупке этого номинала в игре. Если уже покупали, придёт без удвоения.',
    'en', 'The doubling works only on the first purchase of this tier in the game. Bought it before? It arrives without it.',
    'uz', 'Ikki baravar faqat bu nominal oʻyinda birinchi marta olinganda. Avval olgan boʻlsangiz, ikki baravarsiz keladi.'))
WHERE notice -> 'badge' ->> 'ru' = '1-я покупка'
  AND denomination ~ '^(\d+) \+ \1 Diamonds$';

SELECT denomination, notice -> 'badge' ->> 'ru' AS badge, notice -> 'text' ->> 'ru' AS text
FROM skus
WHERE notice -> 'badge' ->> 'ru' IN ('1-я покупка', '×2 в первый раз')
GROUP BY 1, 2, 3 ORDER BY 1;

COMMIT;
