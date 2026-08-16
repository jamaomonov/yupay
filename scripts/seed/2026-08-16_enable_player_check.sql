-- Turn the player check on for the games whose validator actually validates.
--
-- Five products carried a g2b game mapping and no `check` block, so the
-- storefront never offered to confirm the account before payment. Three of
-- them share a game code with a product that already has it working, which is
-- how the gap went unnoticed: `pubg-uc` checks, `pubg-prime` and
-- `pubg-royal-pass` sit on the same `pubgm` code and did not.
--
-- Which games belong here was settled by asking G2B's own validator with a
-- deliberately bogus id (999999999999) rather than by reading
-- `/games/fields`, which only lists the inputs a title takes and says nothing
-- about whether a validator exists behind them:
--
--   pubgm              -> "invalid"   real validator (control: already live)
--   mlbb               -> "invalid"   real validator (control: already live)
--   bloodstrike        -> "invalid"   real validator  <- enabled here
--   whiteout_survival  -> "invalid"   real validator  <- enabled here
--   genshin            -> "valid"     rubber stamp    <- deliberately NOT enabled
--   honkai_star_rail   -> "valid"     rubber stamp    <- deliberately NOT enabled
--   freefire_cis       -> "valid"     rubber stamp    <- deliberately NOT enabled
--
-- Genshin, Honkai Star Rail and Free Fire answer "valid" for an id that cannot
-- exist. A check there would print a green "account confirmed" pill over any
-- typo, immediately before the customer pays — worse than offering no check at
-- all, because it manufactures confidence instead of withholding it. Do not
-- "fix" their missing check without re-running that probe; see
-- `docs/decisions/0031-storefront-player-check.md`.
--
-- All five games take `userid` alone (no server), so `server_field` stays null,
-- matching the block `pubg-uc` already carries.
--
-- Addresses the field **by key**. Idempotent. Aborts if the result is not what
-- it promises.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
--     < scripts/seed/2026-08-16_enable_player_check.sql

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
WHERE p.slug IN (
        'blood-strike-gold',
        'blood-strike-passes',
        'whiteout-survival-frost-stars',
        'pubg-prime',
        'pubg-royal-pass'
      )
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
     WHERE p.slug IN ('blood-strike-gold', 'blood-strike-passes',
                      'whiteout-survival-frost-stars', 'pubg-prime', 'pubg-royal-pass')
       AND NOT (p.required_fields @>
                '[{"key": "player_id", "check": {"provider": "g2b", "server_field": null}}]'::jsonb);

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'player check not applied to: %', bad;
    END IF;
END $$;

COMMIT;
