-- Restore the player-check UI flag on catalog products that lost it.
--
-- Symptom: the "Проверить" (validate player id) button was missing on some
-- products (PUBG UC, Steam wallet, Delta Force coins, every Arena Breakout tier)
-- while present on their sibling "pass" products. The button renders only when a
-- product's required_fields[0].check names a supported provider (g2b/waxpeer);
-- on prod that block was NULL on the affected rows. seed_catalog.py defines the
-- check per game/brand, but prod catalog rows drifted per-product.
--
-- This re-applies the correct check block, brand-scoped + idempotent, so every
-- product of a checkable brand stays consistent (re-running is a no-op). The
-- `->0->>'key'` guards ensure we only touch the expected id field.
--
-- Intentionally EXCLUDED: Free Fire and Genshin Impact — g2b returns
-- "no validation required" for them, so they correctly have no check.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-04_player_check_fields.sql

BEGIN;

-- g2b-validated brands: player_id field -> g2b check.
UPDATE products p
SET required_fields = jsonb_set(
        p.required_fields, '{0,check}',
        '{"provider": "g2b", "server_field": null}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id
  AND b.slug IN ('pubg-mobile', 'delta-force', 'arena-breakout', 'arena-breakout-infinite')
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'player_id';

-- Steam wallet: steam_login field -> waxpeer check.
UPDATE products p
SET required_fields = jsonb_set(
        p.required_fields, '{0,check}',
        '{"provider": "waxpeer", "server_field": null}'::jsonb, true)
FROM brands b
WHERE b.id = p.brand_id
  AND b.slug = 'steam'
  AND jsonb_typeof(p.required_fields) = 'array'
  AND p.required_fields->0->>'key' = 'steam_login';

COMMIT;
