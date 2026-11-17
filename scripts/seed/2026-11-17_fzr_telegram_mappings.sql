-- FazerCards as a second channel for Telegram Stars and Premium (2026-11-17).
-- Copies every NOVA Fragment mapping to fzr unchanged: the sentinels
-- (fragment-stars / fragment-premium), the pack size in quantity and the
-- months in the variant mean the same thing to both adapters.
--
-- Changes no route. fzr is a reserve supplier (RESERVE_SUPPLIERS), so auto
-- routing never picks it; orders move only when an operator sets
-- force_supplier = fzr in sourcing or reassigns a task from the inbox.
-- Re-runnable: an existing fzr mapping on the SKU is left alone.
--
-- Run: docker compose -f docker-compose.prod.yml exec -T postgres \
--        psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 < scripts/seed/2026-11-17_fzr_telegram_mappings.sql

BEGIN;

INSERT INTO sku_supplier_mapping
    (sku_id, supplier_slug, kind, external_product_id, external_variant_id, quantity, extra,
     is_active, updated_by)
SELECT m.sku_id, 'fzr', m.kind, m.external_product_id, m.external_variant_id, m.quantity,
       '{}'::jsonb, true, 'seed:2026-11-17_fzr_telegram'
FROM sku_supplier_mapping m
WHERE m.supplier_slug = 'nova'
  AND m.external_product_id IN ('fragment-stars', 'fragment-premium')
ON CONFLICT (sku_id, supplier_slug) DO NOTHING;

-- Expect one fzr row per NOVA Fragment row (15 on 2026-11-17: 12 Stars, 3 Premium).
SELECT
    count(*) FILTER (WHERE supplier_slug = 'nova') AS nova_rows,
    count(*) FILTER (WHERE supplier_slug = 'fzr') AS fzr_rows
FROM sku_supplier_mapping
WHERE external_product_id IN ('fragment-stars', 'fragment-premium');

COMMIT;
