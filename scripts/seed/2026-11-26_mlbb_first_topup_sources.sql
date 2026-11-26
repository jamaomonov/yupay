-- MLBB: second and third sources for the four first-top-up packs, and all five
-- SKUs handed to smart routing (ADR-0108). Owner, 2026-11-26.
--
-- Why: 50+5 / 150+15 / 250+25 / 500+65 sold 514 times in 30 days with G2B as
-- the only mapping, so neither auto-failover nor smart routing could do
-- anything when G2B refused or got dearer. mlbb-429 had four suppliers but no
-- rule at all (default route = oldest mapping, G2B).
--
-- Checked live 2026-11-26 against each supplier's catalogue (cost per pack):
--   pack        G2B     fzr (first_top_up_bonus)   G-Engine (service 44)
--   50 + 5      0.765   0.76                       0.826  (denom 809)
--   150 + 15    2.305   2.28                       2.448  (denom 811)
--   250 + 25    3.723   3.68                       3.937  (denom 813)
--   500 + 65    7.640   7.56                       8.089  (denom 814)
-- Same packs by name and size on all three. NOVA is a reserve supplier
-- (never picked automatically) and is left out.
--
-- Rules are written on the route orders take today (G2B) with managed = true;
-- the hourly job moves them once a fresh price shows a ≥1 % gap.
--
-- Rollback:
--   DELETE FROM sku_supplier_mapping m USING skus s
--    WHERE s.id = m.sku_id AND s.sku_code IN ('mlbb-55','mlbb-165','mlbb-275','mlbb-565')
--      AND m.supplier_slug IN ('fzr','gengine');
--   DELETE FROM sku_sourcing_rules r USING skus s
--    WHERE s.id = r.sku_id AND r.updated_by = 'seed:2026-11-26_mlbb_first_topup';
--
-- Idempotent. Apply with operator psql.

BEGIN;

CREATE TEMP TABLE src (sku_code text, supplier text, product text, variant text) ON COMMIT DROP;
INSERT INTO src VALUES
    ('mlbb-55',  'fzr',     'mobile_legends_global', '50_5_diamonds_first_top_up_bonus'),
    ('mlbb-165', 'fzr',     'mobile_legends_global', '150_15_diamonds_first_top_up_bonus'),
    ('mlbb-275', 'fzr',     'mobile_legends_global', '250_25_diamonds_first_top_up_bonus'),
    ('mlbb-565', 'fzr',     'mobile_legends_global', '500_65_diamonds_first_top_up_bonus'),
    ('mlbb-55',  'gengine', '44', '809'),
    ('mlbb-165', 'gengine', '44', '811'),
    ('mlbb-275', 'gengine', '44', '813'),
    ('mlbb-565', 'gengine', '44', '814');

INSERT INTO sku_supplier_mapping
    (sku_id, supplier_slug, kind, external_product_id, external_variant_id, quantity, extra,
     is_active, updated_by)
SELECT s.id, x.supplier, 'game', x.product, x.variant, 1, '{}'::jsonb, true,
       'seed:2026-11-26_mlbb_first_topup'
  FROM src x JOIN skus s ON s.sku_code = x.sku_code
ON CONFLICT (sku_id, supplier_slug) DO NOTHING;

INSERT INTO sku_sourcing_rules (sku_id, mode, supplier_slug, updated_by, managed)
SELECT s.id, 'force_supplier', 'g2b', 'seed:2026-11-26_mlbb_first_topup', true
  FROM skus s
 WHERE s.sku_code IN ('mlbb-55', 'mlbb-165', 'mlbb-275', 'mlbb-565', 'mlbb-429')
ON CONFLICT (sku_id) DO NOTHING;

SELECT s.sku_code,
       string_agg(m.supplier_slug, ',' ORDER BY m.supplier_slug) AS suppliers,
       r.supplier_slug AS route, r.managed
  FROM skus s
  JOIN sku_supplier_mapping m ON m.sku_id = s.id AND m.is_active
  LEFT JOIN sku_sourcing_rules r ON r.sku_id = s.id
 WHERE s.sku_code IN ('mlbb-55', 'mlbb-165', 'mlbb-275', 'mlbb-565', 'mlbb-429')
 GROUP BY s.sku_code, r.supplier_slug, r.managed
 ORDER BY s.sku_code;

COMMIT;
