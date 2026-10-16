-- Put the imported Mobile Legends and Magic Chess regions on the storefront (ADR-0099).
--
-- Run AFTER the release carrying migration 0101_brand_regions is deployed:
-- before it, the storefront lists every retail brand as its own card, and
-- these would show up as eleven separate games.
--
-- The brands came from the bulk supplier import as B2B-only. Migration 0101
-- linked them to their main brand; this makes them retail-visible, which puts
-- each on its game's region switcher. To take a region off again, set its
-- visible_retail back to false.
--
-- Idempotent. Apply with operator psql:
--   sudo docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay \
--     < scripts/seed/2026-10-16_game_regions_retail.sql

BEGIN;

UPDATE brands
SET visible_retail = true, updated_at = now()
WHERE region_parent_id IS NOT NULL
  AND slug IN (
    'mobile-legends-ph', 'mobile-legends-my', 'mobile-legends-sg', 'mobile-legends-id',
    'mobile-legends-tr', 'mobile-legends-us', 'mobile-legends-br',
    'magic-chess-gogo-my', 'magic-chess-gogo-ph', 'magic-chess-gogo-tr'
  );

SELECT p.slug AS game, c.region_code, c.slug, c.visible_retail
FROM brands c JOIN brands p ON p.id = c.region_parent_id
ORDER BY 1, 2;

COMMIT;
