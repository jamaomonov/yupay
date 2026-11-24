-- Smart routing (ADR-0108): hand every rule that has a real choice to the hourly job.
-- A force_supplier rule on fzr / g2b / nova whose SKU has at least two active
-- supplier mappings (3637 on prod, 2026-11-24). Rules on foxreload, gengine,
-- manual and single-supplier SKUs stay pinned. Needs migration 0115.
-- Start the job in «Только смотреть» for a week, then «Включено». Idempotent.
BEGIN;

UPDATE sku_sourcing_rules r SET managed = true
WHERE r.mode = 'force_supplier'
  AND r.supplier_slug IN ('fzr', 'g2b', 'nova')
  AND NOT r.managed
  AND (
    SELECT count(*) FROM sku_supplier_mapping m
    WHERE m.sku_id = r.sku_id AND m.is_active
      AND m.supplier_slug IN ('fzr', 'g2b', 'nova', 'gengine', 'foxreload')
  ) >= 2;

SELECT supplier_slug, count(*) FILTER (WHERE managed) AS managed, count(*) AS rules
FROM sku_sourcing_rules WHERE mode = 'force_supplier' GROUP BY 1 ORDER BY 1;

COMMIT;
