-- Put the player check back on the field it verifies, for `mlbb-diamonds-ru`.
--
-- Symptom: a Russian-region player entering a correct id (player 1313232551,
-- server 6618) never passed verification on the storefront, while G2B's own UI
-- validated the same pair against `mlbb_ru` fine.
--
-- Cause: prod's `mlbb-diamonds-ru` carried its `check` block on the **server**
-- field, with `server_field: "server"` — pointing at itself. The storefront
-- sends the checked field's own value as `player_id` and the field named by
-- `server_field` as `server_id`, so it asked G2B to verify player 6618 on
-- server 6618. That answers "invalid" for everyone, forever. The game_code
-- resolution was never involved: the RU product maps to `mlbb_ru` correctly.
--
-- Why it matters beyond a dead button: the brand FAQ tells customers that a
-- missing nickname means they need the *other* region's product. A check that
-- can never succeed therefore steered every Russian buyer at the global
-- product — the exact mistake ADR-0048 built this check to prevent.
--
-- The drift is a hand edit in the admin, not a script: seed_catalog.py and
-- scripts/seed/2026-08-09_mobile_legends_import.py both emit the check on
-- `player_id`. `ProductCreate`/`ProductUpdate` now reject a `server_field`
-- that names the field itself or a key no field defines, so this cannot be
-- re-entered through the admin.
--
-- Addresses fields **by key**, never by array index — indexing is how
-- scripts/seed/2026-08-04_player_check_fields.sql could land a block on
-- whichever field happened to be first.
--
-- Idempotent: re-running rewrites the same shape. Field order is preserved.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-16_mlbb_ru_check_field.sql

BEGIN;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id'
                           THEN jsonb_set(
                                    elem, '{check}',
                                    '{"provider": "g2b", "server_field": "server"}'::jsonb,
                                    true)
                       ELSE jsonb_set(elem, '{check}', 'null'::jsonb, true)
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE p.slug = 'mlbb-diamonds-ru'
  -- Only touch the shape this fix is written for: both keys present. A product
  -- that has drifted some other way should be looked at, not silently rewritten.
  AND p.required_fields @> '[{"key": "player_id"}]'::jsonb
  AND p.required_fields @> '[{"key": "server"}]'::jsonb;

-- Fails the transaction if the result is not what this script promises, so a
-- partial or unexpected state is never committed.
DO $$
DECLARE
    checked_key text;
    server_field text;
BEGIN
    SELECT elem->>'key', elem->'check'->>'server_field'
      INTO checked_key, server_field
      FROM products p,
           LATERAL jsonb_array_elements(p.required_fields) AS elem
     WHERE p.slug = 'mlbb-diamonds-ru'
       AND jsonb_typeof(elem->'check') = 'object';

    IF checked_key IS DISTINCT FROM 'player_id' OR server_field IS DISTINCT FROM 'server' THEN
        RAISE EXCEPTION
            'mlbb-diamonds-ru check landed on %, server_field=% — expected player_id/server',
            checked_key, server_field;
    END IF;
END $$;

COMMIT;
