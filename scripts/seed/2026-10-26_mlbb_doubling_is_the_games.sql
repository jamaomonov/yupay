-- MLBB first-top-up notice, third pass: say the doubling is the game's, not ours.
--
-- 2026-10-26 a buyer paid for «500 + 65 Diamonds», got 500 + 65 (he had bought
-- that tier before) and wrote to support «вы обманщики, 500+500 не дали»: the
-- tile badge «×2 в первый раз» and a text that opened with «алмазы удвоятся»
-- read as a YuPay promotion. Now the badge names the game, and the text leads
-- with what is guaranteed, then the game's own doubling as a conditional.
--
-- Touches only SKUs that carry one of the two first-top-up badges. Idempotent.
-- Apply on prod (operator psql):
--   docker compose -p yupay-prod exec -T postgres \
--     psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 -f - < scripts/seed/2026-10-26_mlbb_doubling_is_the_games.sql

BEGIN;

-- «500 + 65 Diamonds»: the pack is what arrives; ×2 is up to the game.
UPDATE skus AS s SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', 'Акция игры', 'en', 'Game promo', 'uz', 'Oʻyin aksiyasi'),
  'text', jsonb_build_object(
    'ru', 'Придёт ' || n.b || ' + ' || n.x || ' алмазов. Если вы ни разу не покупали этот номинал в игре, игра сама удвоит его до ' || n.b || ' + ' || n.b || '. Это акция игры, не YuPay.',
    'en', 'You get ' || n.b || ' + ' || n.x || ' diamonds. If you have never bought this tier in the game, the game itself doubles it to ' || n.b || ' + ' || n.b || '. This is the game''s promo, not YuPay''s.',
    'uz', n.b || ' + ' || n.x || ' olmos keladi. Bu nominalni oʻyinda hech qachon olmagan boʻlsangiz, oʻyinning oʻzi uni ' || n.b || ' + ' || n.b || ' gacha ikki baravar qiladi. Bu YuPay emas, oʻyin aksiyasi.'))
FROM (
  SELECT id,
         substring(denomination from '^(\d+) \+') AS b,
         substring(denomination from '\+ (\d+) Diamonds$') AS x
  FROM skus
  WHERE notice -> 'badge' ->> 'ru' IN ('×2 в первый раз', 'Акция игры')
    AND denomination ~ '^\d+ \+ \d+ Diamonds$'
) AS n
WHERE s.id = n.id AND n.b <> n.x;

-- «50 + 50 Diamonds» (ID): named by the doubled value, so a repeat buyer gets less.
UPDATE skus SET updated_at = now(), notice = jsonb_build_object(
  'badge', jsonb_build_object('ru', 'Акция игры', 'en', 'Game promo', 'uz', 'Oʻyin aksiyasi'),
  'text', jsonb_build_object(
    'ru', 'Удвоение даёт сама игра и только при первой покупке этого номинала. Если уже покупали, придёт без удвоения. Это акция игры, не YuPay.',
    'en', 'The game itself doubles it, and only on the first purchase of this tier. Bought it before? It arrives without the doubling. This is the game''s promo, not YuPay''s.',
    'uz', 'Ikki baravarni oʻyinning oʻzi beradi va faqat bu nominal birinchi marta olinganda. Avval olgan boʻlsangiz, ikki baravarsiz keladi. Bu YuPay emas, oʻyin aksiyasi.'))
WHERE notice -> 'badge' ->> 'ru' IN ('1-я покупка', 'Акция игры')
  AND denomination ~ '^(\d+) \+ \1 Diamonds$';

SELECT denomination, notice -> 'badge' ->> 'ru' AS badge, notice -> 'text' ->> 'ru' AS text, count(*)
FROM skus
WHERE notice -> 'badge' ->> 'ru' IN ('1-я покупка', '×2 в первый раз', 'Акция игры')
GROUP BY 1, 2, 3 ORDER BY 1;

COMMIT;
