-- Give the Steam wallet SKU its NOVA mapping, so NOVA becomes a switchable
-- second channel for top-ups the way ADR-0082 designed it.
--
-- The NOVA Steam code shipped on 2026-09-18 and has never had a row to act on.
-- `steam-wallet-usd` carries exactly one mapping today — gengine, category "2" —
-- plus a `force_supplier = waxpeer` rule, so Waxpeer fulfils and G-Engine is the
-- documented fallback. NOVA is absent entirely, which is why it does not appear
-- on the brand sourcing screen and cannot be switched to.
--
-- **This changes nothing about where orders go.** The `force_supplier = waxpeer`
-- rule still decides the route, and NOVA is a reserve (ADR-0081) that automatic
-- routing never picks even without a rule. The row only makes the channel
-- *available*: visible on the brand screen beside the others, and reachable by
-- an explicit switch when somebody decides to make one.
--
-- Why these exact values:
--
--   kind = 'game'                       `nova._mapping_for` filters on it, and
--                                       the CHECK allows only voucher/game/gift
--                                       — the sentinel is not a fourth kind.
--   external_product_id = 'steam-topup' `NOVA_STEAM_SENTINEL`. `nova._fulfill`
--                                       compares the category id against it and
--                                       branches into `_fulfill_steam`, which
--                                       posts {steamLogin, currency, amount} to
--                                       /api/v2/steam-topup/order instead of a
--                                       catalogue offer.
--   external_variant_id = NULL          The Steam branch returns before reading
--                                       an offer id; there is no offer to name.
--
-- The cost sync skips this row on purpose (`cost_lookup` has no catalogue price
-- for the sentinel), so it will never write `cost_usdt` on a variable-amount SKU.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-18_nova_steam_mapping.sql
--
-- Idempotent: re-running updates the same row rather than failing on the
-- composite primary key.

BEGIN;

INSERT INTO sku_supplier_mapping (
    sku_id, supplier_slug, kind, external_product_id, external_variant_id,
    quantity, extra, is_active, updated_by
)
SELECT s.id, 'nova', 'game', 'steam-topup', NULL, 1, '{}'::jsonb, true, 'seed:nova-steam'
  FROM skus s
 WHERE s.sku_code = 'steam-wallet-usd'
ON CONFLICT (sku_id, supplier_slug) DO UPDATE
   SET kind = EXCLUDED.kind,
       external_product_id = EXCLUDED.external_product_id,
       external_variant_id = EXCLUDED.external_variant_id,
       is_active = true,
       updated_by = EXCLUDED.updated_by,
       updated_at = CURRENT_TIMESTAMP;

-- Show what the SKU now looks like, and prove the route did not move.
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
