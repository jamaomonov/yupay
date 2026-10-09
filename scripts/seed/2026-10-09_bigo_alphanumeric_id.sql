-- Bigo Live: accept letters in the Bigo ID.
--
-- A customer typed `Lexus0011` and the «Проверить» button stayed disabled: the
-- field's pattern was `^[0-9]{5,20}$`, copied from Honor of Kings and Likee by
-- `2026-09-21_hok_bigo_likee_import.py`. Bigo lets a user pick a custom ID with
-- letters. Probed through the storefront check on 2026-10-09:
--
--   Lexus0011   -> valid, nickname "GANGSTER"
--   lexus0011   -> valid, same account (case-insensitive upstream)
--   Zz9qXq7Lw2  -> invalid
--
-- So G2B's `bigo` validator handles letters and still rejects ids that do not
-- exist. The same pattern is enforced server-side at order creation
-- (`orders/validation.py`), so this is a data fix, not a frontend one.
--
-- New pattern: letters, digits, dot, underscore and hyphen, 3–32 characters.
-- The help text loses "the ID is digits only" in all three locales.
--
-- Idempotent. Aborts if the result is not what it promises.
--
-- Apply on prod (operator psql):
--   docker exec -i yupay-prod-postgres-1 psql -v ON_ERROR_STOP=1 \
--     -U yupay_app -d yupay < scripts/seed/2026-10-09_bigo_alphanumeric_id.sql

BEGIN;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id' THEN
                           elem
                           || jsonb_build_object('pattern', '^[A-Za-z0-9._-]{3,32}$')
                           || jsonb_build_object('help_text', jsonb_build_object(
                                'ru',
                                'Откройте Bigo Live и перейдите в профиль — ID показан под вашим именем.' || E'\n'
                                || 'Скопируйте ID, не набирайте вручную: в нём бывают буквы и цифры, а одна ошибка отправит покупку другому человеку.' || E'\n'
                                || 'Пароль не нужен — пополнение идёт по публичному ID.',
                                'en',
                                'Open Bigo Live and go to your profile — the ID is shown under your name.' || E'\n'
                                || 'Copy the ID instead of retyping it: it can contain letters and digits, and one wrong character sends the purchase to somebody else.' || E'\n'
                                || 'No password needed — the top-up goes by public ID.',
                                'uz',
                                'Bigo Live ni oching va profilingizga oʻting — ID ismingiz ostida koʻrsatilgan.' || E'\n'
                                || 'ID ni qoʻlda termay, nusxa oling: unda harflar va raqamlar boʻlishi mumkin, bitta xato esa xaridni boshqa odamga yuboradi.' || E'\n'
                                || 'Parol kerak emas — toʻldirish ommaviy ID orqali.'
                              ))
                       ELSE elem
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE p.slug = 'bigo-diamonds'
  AND p.required_fields @> '[{"key": "player_id"}]'::jsonb;

DO $$
DECLARE
    f jsonb;
BEGIN
    SELECT elem INTO f
    FROM products p, jsonb_array_elements(p.required_fields) elem
    WHERE p.slug = 'bigo-diamonds' AND elem->>'key' = 'player_id';
    IF f IS NULL THEN
        RAISE EXCEPTION 'bigo-diamonds has no player_id field';
    END IF;
    IF f->>'pattern' <> '^[A-Za-z0-9._-]{3,32}$' THEN
        RAISE EXCEPTION 'pattern not applied: %', f->>'pattern';
    END IF;
    IF 'Lexus0011' !~ (f->>'pattern') OR '123456789' !~ (f->>'pattern') THEN
        RAISE EXCEPTION 'pattern rejects a real Bigo ID';
    END IF;
    IF (f->'help_text'->>'ru') LIKE '%только из цифр%'
       OR (f->'help_text'->>'en') LIKE '%digits only%'
       OR (f->'help_text'->>'uz') LIKE '%faqat raqamlardan%' THEN
        RAISE EXCEPTION 'help text still says digits only';
    END IF;
    IF f->'check' IS NULL THEN
        RAISE EXCEPTION 'player check was lost';
    END IF;
END $$;

COMMIT;
