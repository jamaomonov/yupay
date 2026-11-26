-- Smart routing (ADR-0108): every SKU with a real choice of supplier goes to the
-- hourly job, except Steam. Owner, 2026-11-26: «всё, кроме стима, пусть
-- регулирует автовыбор».
--
-- Before this, three kinds of SKU sat outside the job although two or more
-- suppliers could sell them:
--   1. force_supplier pinned to G-Engine (the 2026-11-24 seed left those out);
--   2. legacy mode 'auto' rules (IMO, Whiteout Survival);
--   3. SKUs with no rule at all — routed to the oldest non-reserve mapping.
-- (1) is flipped to managed. (2) and (3) get a managed force_supplier rule
-- written on the route orders take TODAY, so nothing moves until the job sees
-- a fresh ≥1 % gap or the current supplier cannot sell.
--
-- "Today's route" is exactly what sourcing.service._pick_auto_mapping_slug
-- answers: the oldest active mapping that is neither a reserve supplier (fzr,
-- nova) nor catalogue-delisted. A SKU with no such mapping (only fzr/nova) gets
-- the cheapest fresh fzr/nova price instead; the job then manages it like any
-- other.
--
-- Untouched on purpose: Steam (FoxReload split, ADR-0104), 'manual' and
-- 'force_inventory' rules (not a choice between suppliers), every rule an
-- operator pinned by hand after this runs.
--
-- Rollback:
--   UPDATE sku_sourcing_rules SET managed = false
--    WHERE managed AND mode = 'force_supplier' AND supplier_slug = 'gengine'
--      AND updated_by IS DISTINCT FROM 'seed:2026-11-26_smart_everything';  -- (1)
--   DELETE FROM sku_sourcing_rules WHERE updated_by = 'seed:2026-11-26_smart_everything';
--   -- then re-insert the 12 'auto' rules from the SELECT printed by the dry run.
--
-- Idempotent. Apply with operator psql.

BEGIN;

CREATE TEMP TABLE choice ON COMMIT DROP AS
WITH alt AS (
    SELECT m.sku_id, count(DISTINCT m.supplier_slug) AS n
      FROM sku_supplier_mapping m
     WHERE m.is_active
       -- A delisted mapping still counts: the job treats it as "cannot sell"
       -- and picks it up again the hour the supplier relists the position.
       AND m.supplier_slug IN ('fzr', 'g2b', 'nova', 'gengine')
     GROUP BY m.sku_id
)
SELECT s.id AS sku_id, s.sku_code, r.mode AS old_mode, r.supplier_slug AS old_supplier,
       coalesce(
           (SELECT m.supplier_slug FROM sku_supplier_mapping m
             WHERE m.sku_id = s.id AND m.is_active
               AND m.supplier_slug IN ('g2b', 'gengine')
               AND NOT coalesce((m.extra ->> 'catalog_watch_deactivated')::boolean, false)
             ORDER BY m.created_at, m.supplier_slug LIMIT 1),
           (SELECT ps.supplier_slug FROM supplier_price_state ps
              JOIN sku_supplier_mapping m
                ON m.sku_id = ps.sku_id AND m.supplier_slug = ps.supplier_slug AND m.is_active
             WHERE ps.sku_id = s.id AND ps.supplier_slug IN ('fzr', 'nova')
               AND ps.cost_usdt IS NOT NULL
             ORDER BY ps.cost_usdt, ps.supplier_slug LIMIT 1),
           'fzr'
       ) AS route
  FROM skus s
  JOIN alt ON alt.sku_id = s.id AND alt.n >= 2
  JOIN products p ON p.id = s.product_id
  JOIN brands b ON b.id = p.brand_id
  LEFT JOIN sku_sourcing_rules r ON r.sku_id = s.id
 WHERE s.active
   AND b.slug <> 'steam'
   AND (r.sku_id IS NULL OR r.mode = 'auto');

-- What the legacy 'auto' rules looked like, for the rollback.
SELECT sku_code, old_mode, route FROM choice WHERE old_mode = 'auto' ORDER BY sku_code;

-- (1) G-Engine pins with an alternative.
UPDATE sku_sourcing_rules r SET managed = true, updated_at = now()
 WHERE r.mode = 'force_supplier' AND r.supplier_slug = 'gengine' AND NOT r.managed
   AND NOT EXISTS (SELECT 1 FROM skus s JOIN products p ON p.id = s.product_id
                     JOIN brands b ON b.id = p.brand_id
                    WHERE s.id = r.sku_id AND b.slug = 'steam')
   AND (SELECT count(DISTINCT m.supplier_slug) FROM sku_supplier_mapping m
         WHERE m.sku_id = r.sku_id AND m.is_active
           AND m.supplier_slug IN ('fzr', 'g2b', 'nova', 'gengine')) >= 2;

-- (2) + (3) legacy 'auto' and no rule.
INSERT INTO sku_sourcing_rules (sku_id, mode, supplier_slug, updated_by, managed)
SELECT sku_id, 'force_supplier', route, 'seed:2026-11-26_smart_everything', true FROM choice
ON CONFLICT (sku_id) DO UPDATE
   SET mode = 'force_supplier', supplier_slug = EXCLUDED.supplier_slug,
       updated_by = EXCLUDED.updated_by, managed = true, updated_at = now()
 WHERE sku_sourcing_rules.mode = 'auto';

-- What is still outside the job and has a choice: should be Steam only.
WITH alt AS (
    SELECT m.sku_id, count(DISTINCT m.supplier_slug) AS n FROM sku_supplier_mapping m
     WHERE m.is_active AND m.supplier_slug IN ('fzr', 'g2b', 'nova', 'gengine', 'foxreload')
     GROUP BY m.sku_id)
SELECT b.slug AS brand, coalesce(r.mode, '(no rule)') AS mode, r.supplier_slug, count(*)
  FROM skus s JOIN alt ON alt.sku_id = s.id AND alt.n >= 2
  JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
  LEFT JOIN sku_sourcing_rules r ON r.sku_id = s.id
 WHERE s.active AND NOT coalesce(r.managed, false)
 GROUP BY 1, 2, 3 ORDER BY 4 DESC;

SELECT route, count(*) FROM choice GROUP BY 1 ORDER BY 2 DESC;

COMMIT;
