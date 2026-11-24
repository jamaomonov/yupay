-- Give the Steam wallet SKU its FoxReload mapping (ADR-0107).
--
-- FoxReload sells Steam by login as «Steam Wallet 1 USD (Global)», one unit per
-- dollar, 1-175 a line. `foxreload._product_id` reads the product id from this
-- row, and the `force_supplier` guard refuses a rule naming a supplier with no
-- active mapping, so the row must exist before the switch.
--
-- **This changes nothing about where orders go.** On 2026-11-24 the SKU's rule is
-- `force_supplier = fzr`; the row only makes FoxReload available on the brand
-- sourcing screen. The switch is the commented block at the end — run it (or set
-- it in the admin) once FOXRELOAD_API_KEY is on prod and the USD balance funded.
--
-- Why these exact values:
--
--   kind = 'game'                 The CHECK allows only voucher/game/gift; a
--                                 top-up is 'game'.
--   external_product_id           Their product id, read off
--                                 GET /api/products/?categoryId=gaming-services-steam-wallet-top-up
--                                 on 2026-11-24. If they replace the product,
--                                 update this column — nothing else.
--   external_variant_id = NULL    The adapter buys `amount` units of the product;
--                                 there is no variant (integrations.service
--                                 treats foxreload as amount-priced).
--   quantity = 1                  Unused for Steam: the dollar count comes from
--                                 the line's amount (`foxreload.steam_quantity`).
--
-- Apply (prod):
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-11-24_foxreload_steam_mapping.sql
--
-- Idempotent: re-running updates the same row.

BEGIN;

INSERT INTO sku_supplier_mapping (
    sku_id, supplier_slug, kind, external_product_id, external_variant_id,
    quantity, extra, is_active, updated_by
)
SELECT s.id, 'foxreload', 'game', 'product_01kjp6vtmjf8rbbxw88719wz3b', NULL, 1,
       '{}'::jsonb, true, 'seed:foxreload-steam'
  FROM skus s
 WHERE s.sku_code = 'steam-wallet-usd'
ON CONFLICT (sku_id, supplier_slug) DO UPDATE
   SET kind = EXCLUDED.kind,
       external_product_id = EXCLUDED.external_product_id,
       external_variant_id = EXCLUDED.external_variant_id,
       quantity = EXCLUDED.quantity,
       is_active = true,
       updated_by = EXCLUDED.updated_by,
       updated_at = CURRENT_TIMESTAMP;

-- What the SKU now carries, and proof the route did not move.
SELECT m.supplier_slug, m.kind, m.external_product_id, m.is_active
  FROM sku_supplier_mapping m
  JOIN skus s ON s.id = m.sku_id
 WHERE s.sku_code = 'steam-wallet-usd'
 ORDER BY m.supplier_slug;

SELECT r.mode, r.supplier_slug AS route_still
  FROM sku_sourcing_rules r
  JOIN skus s ON s.id = r.sku_id
 WHERE s.sku_code = 'steam-wallet-usd';

COMMIT;

-- ---------------------------------------------------------------------------
-- The switch (run separately, after the key and the USD balance are in place).
-- Whole dollars 1-175 then go to FoxReload; cents and over-cap lines go to
-- FOXRELOAD_OVERFLOW_SUPPLIER (env, default waxpeer). Back: set supplier_slug to
-- the previous value (was 'fzr' on 2026-11-24).
--
-- UPDATE sku_sourcing_rules r
--    SET supplier_slug = 'foxreload', updated_at = CURRENT_TIMESTAMP
--   FROM skus s
--  WHERE s.id = r.sku_id AND s.sku_code = 'steam-wallet-usd'
--    AND r.mode = 'force_supplier';
