-- scripts/seed/2026-10-27_standoff2_variants.sql
--
-- Standoff 2 as ONE game in the catalogue, two pages inside (migration 0108):
--
--   standoff-2-id  main variant `id`    — the catalogue tile, opened by default
--   standoff-2     variant `promo`      — its own page (the search history), not
--                                         a tile; linked from the switcher
--
-- Both pages show «По ID / Промокод» as links. The by-id brand is renamed to
-- plain «Standoff 2» — it is the game's tile now; the switcher says how it is
-- bought. Its search titles (2026-10-27_standoff2_by_id_seo.sql) are unchanged.
-- Run after the deploy that carries migration 0108. Idempotent.
--
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -v ON_ERROR_STOP=1 -U yupay_app -d yupay < scripts/seed/2026-10-27_standoff2_variants.sql

BEGIN;

UPDATE brands SET variant_code = 'id', variant_parent_id = NULL, updated_at = now()
WHERE slug = 'standoff-2-id';

UPDATE brands SET
    variant_code = 'promo',
    variant_parent_id = (SELECT id FROM brands WHERE slug = 'standoff-2-id'),
    updated_at = now()
WHERE slug = 'standoff-2';

UPDATE brand_translations SET name = 'Standoff 2'
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2-id');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM brands c JOIN brands p ON p.id = c.variant_parent_id
        WHERE c.slug = 'standoff-2' AND p.slug = 'standoff-2-id'
    ) THEN
        RAISE EXCEPTION 'standoff 2 variants did not land';
    END IF;
END $$;

COMMIT;
