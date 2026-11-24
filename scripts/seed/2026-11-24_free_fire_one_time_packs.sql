-- Free Fire Level Up Packages/Passes are one-time packs (ADR-0108, owner 2026-11-24):
-- signed-in buyers only, a supplier refusal refunds to the YuPay balance at once,
-- never handed to another supplier. Every Free Fire brand (main and regional).
-- Needs migration 0113. Idempotent.
BEGIN;

UPDATE skus s SET one_time_pack = true
FROM products p JOIN brands b ON b.id = p.brand_id
WHERE p.id = s.product_id
  AND b.slug LIKE '%free-fire%'
  AND s.denomination ILIKE 'Level Up Pa%'
  AND NOT s.one_time_pack;

SELECT b.slug, count(*) FILTER (WHERE s.one_time_pack) AS one_time, count(*) AS level_up
FROM skus s JOIN products p ON p.id = s.product_id JOIN brands b ON b.id = p.brand_id
WHERE b.slug LIKE '%free-fire%' AND s.denomination ILIKE 'Level Up Pa%'
GROUP BY b.slug ORDER BY b.slug;

COMMIT;
