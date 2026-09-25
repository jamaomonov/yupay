-- Bigo Live: turn on the G2B player check, and fix the where-to-find-your-ID
-- help that read Russian inside English and Uzbek on three products.
--
-- 1. The check. ADR-0031 withholds `check` from any G2B title that answers
--    "valid" to an id that cannot exist. `bigo` was probed on 2026-09-25 from
--    production, through the same client the storefront uses:
--
--      the id on a completed Bigo order (#1816974)  -> valid, nickname returned
--      9 random 10- and 12-digit ids                -> invalid, all 9
--      999999999999 / 888888888888 / 123456789012   -> valid, each with its
--                                                      own, different nickname
--
--    The last three are vanity ids that belong to real accounts, not a rubber
--    stamp: a stamp answers every id alike. Real validator — enabled here.
--    Bigo takes the id alone, so `server_field` is null, as for Free Fire.
--
-- 2. The help text. `2026-09-21_hok_bigo_likee_import.py` passed one Russian
--    phrase for "where the ID is" into all three locales, so English said
--    "the ID is shown под вашим именем" on Bigo and Likee, and "в профиле
--    рядом с именем" on Honor of Kings; Uzbek likewise. The script is fixed
--    in the same change; this rewrites the rows it already created.
--
-- Addresses the field by key. Idempotent. Aborts if the result is not what
-- it promises.
--
-- Apply on prod (operator psql):
--   docker exec -i yupay-prod-postgres-1 psql -v ON_ERROR_STOP=1 \
--     -U yupay_app -d yupay < scripts/seed/2026-09-25_bigo_player_check.sql

BEGIN;

CREATE TEMP TABLE _where_fix (ru text, en text, uz text) ON COMMIT DROP;
INSERT INTO _where_fix VALUES
    ('под вашим именем',          'under your name',   'ismingiz ostida'),
    ('в профиле рядом с именем',  'next to your name', 'ismingiz yonida');

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id' THEN
                           jsonb_set(
                               jsonb_set(
                                   elem, '{help_text,en}',
                                   to_jsonb((SELECT coalesce(
                                       max(replace(elem->'help_text'->>'en', w.ru, w.en))
                                           FILTER (WHERE strpos(elem->'help_text'->>'en', w.ru) > 0),
                                       elem->'help_text'->>'en') FROM _where_fix w))),
                               '{help_text,uz}',
                               to_jsonb((SELECT coalesce(
                                   max(replace(elem->'help_text'->>'uz', w.ru, w.uz))
                                       FILTER (WHERE strpos(elem->'help_text'->>'uz', w.ru) > 0),
                                   elem->'help_text'->>'uz') FROM _where_fix w)))
                       ELSE elem
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE p.slug IN ('bigo-diamonds', 'likee-diamonds', 'hok-tokens')
  AND p.required_fields @> '[{"key": "player_id"}]'::jsonb;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id'
                           THEN jsonb_set(elem, '{check}',
                                          '{"provider": "g2b", "server_field": null}'::jsonb, true)
                       ELSE elem
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE p.slug = 'bigo-diamonds'
  AND p.required_fields @> '[{"key": "player_id"}]'::jsonb;

DO $$
DECLARE
    bad text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM products
         WHERE slug = 'bigo-diamonds'
           AND required_fields @>
               '[{"key": "player_id", "check": {"provider": "g2b", "server_field": null}}]'::jsonb
    ) THEN
        RAISE EXCEPTION 'player check not applied to bigo-diamonds';
    END IF;

    SELECT string_agg(p.slug || '/' || v.loc, ', ')
      INTO bad
      FROM products p
     CROSS JOIN LATERAL jsonb_array_elements(p.required_fields) f
     CROSS JOIN (VALUES ('en'), ('uz')) v(loc)
     WHERE p.slug IN ('bigo-diamonds', 'likee-diamonds', 'hok-tokens')
       AND (f->'help_text'->>v.loc) ~ '[А-Яа-яЁё]';

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'Cyrillic still in en/uz help text: %', bad;
    END IF;
END $$;

COMMIT;
