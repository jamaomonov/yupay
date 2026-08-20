-- Turn the player check on for Free Fire — G2B's `freefire_cis` validator
-- stopped rubber-stamping.
--
-- ADR-0031 probed every G2B title with a bogus id (999999999999) and found
-- `freefire_cis` answering "valid" to it, alongside Genshin Impact and Honkai
-- Star Rail — a green "account confirmed" pill over any typo, right before
-- the customer pays, so `check` was deliberately withheld from `free-fire-*`
-- (see `scripts/seed/2026-08-04_player_check_fields.sql` and
-- `scripts/seed/2026-08-16_enable_player_check.sql`, which enabled the same
-- check for other titles but explicitly excluded this one).
--
-- Re-probed 2026-08-20 at the reporting supplier contact's word:
--
--   freefire_cis -> "invalid"   real validator now   <- enabled here
--
-- `seed_catalog.py` was updated in the same change for fresh environments;
-- this script re-applies the check to rows already seeded on prod/staging.
-- Free Fire takes `userid` alone (no server), so `server_field` stays null,
-- matching the block every other g2b-checkable brand carries.
--
-- Addresses the field **by key**. Idempotent. Aborts if the result is not
-- what it promises.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
--     < scripts/seed/2026-08-20_enable_free_fire_player_check.sql

BEGIN;

UPDATE products p
SET required_fields = (
        SELECT jsonb_agg(
                   CASE
                       WHEN elem->>'key' = 'player_id'
                           THEN jsonb_set(
                                    elem, '{check}',
                                    '{"provider": "g2b", "server_field": null}'::jsonb,
                                    true)
                       ELSE elem
                   END
                   ORDER BY ord)
        FROM jsonb_array_elements(p.required_fields) WITH ORDINALITY AS t(elem, ord)
    )
WHERE p.slug IN ('free-fire-diamonds', 'free-fire-membership')
  -- Only the shape this fix is written for. A product without the field has
  -- drifted some other way and should be looked at, not rewritten blind.
  AND p.required_fields @> '[{"key": "player_id"}]'::jsonb;

DO $$
DECLARE
    bad text;
BEGIN
    SELECT string_agg(p.slug, ', ')
      INTO bad
      FROM products p
     WHERE p.slug IN ('free-fire-diamonds', 'free-fire-membership')
       AND NOT (p.required_fields @>
                '[{"key": "player_id", "check": {"provider": "g2b", "server_field": null}}]'::jsonb);

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'player check not applied to: %', bad;
    END IF;
END $$;

COMMIT;
