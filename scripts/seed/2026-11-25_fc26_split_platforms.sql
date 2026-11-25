-- FC 26 Points: undo the merge of two different products (2026-11-25).
--
-- 2026-11-25_storefront5_mapping_fixes.py copied the FazerCards mappings of
-- `ea-sports-fc-26-ea-points` onto `ea-sports-fc-26`, taking them for the same
-- product imported twice. They are not: G-Engine's «EA SPORTS FC 26 Global»
-- (`ea-sports-fc-26`) is an **Xbox** gift card per its own catalogue text, and
-- FazerCards' «EA SPORTS FC 26 (EA, Points)» is an EA app (PC) card. A SKU with
-- both could hand an Xbox buyer a PC code by smart routing or failover.
--
-- Switches the FazerCards mappings off on the Xbox brand, pins its rules back to
-- G-Engine (not managed), and names both brands by platform.
-- Idempotent.
BEGIN;

UPDATE sku_supplier_mapping m SET is_active = false, updated_at = now()
  FROM skus s JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
 WHERE m.sku_id = s.id AND b.slug = 'ea-sports-fc-26' AND m.supplier_slug = 'fzr';

UPDATE sku_sourcing_rules r SET managed = false, supplier_slug = 'gengine',
       mode = 'force_supplier', updated_at = now()
  FROM skus s JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
 WHERE r.sku_id = s.id AND b.slug = 'ea-sports-fc-26';

UPDATE brand_translations t SET name = CASE t.locale
         WHEN 'ru' THEN 'EA SPORTS FC 26 Points (Xbox)'
         WHEN 'en' THEN 'EA SPORTS FC 26 Points (Xbox)'
         ELSE 'EA SPORTS FC 26 Points (Xbox)' END
  FROM brands b WHERE b.id = t.brand_id AND b.slug = 'ea-sports-fc-26';
UPDATE brand_translations t SET name = CASE t.locale
         WHEN 'ru' THEN 'EA SPORTS FC 26 Points (ПК, EA app)'
         WHEN 'en' THEN 'EA SPORTS FC 26 Points (PC, EA app)'
         ELSE 'EA SPORTS FC 26 Points (PK, EA app)' END
  FROM brands b WHERE b.id = t.brand_id AND b.slug = 'ea-sports-fc-26-ea-points';

SELECT b.slug, m.supplier_slug, m.is_active, count(*)
  FROM sku_supplier_mapping m JOIN skus s ON s.id = m.sku_id
  JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
 WHERE b.slug LIKE 'ea-sports-fc-26%' GROUP BY 1, 2, 3 ORDER BY 1, 2;

COMMIT;
