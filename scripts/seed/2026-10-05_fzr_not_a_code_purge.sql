-- Purge what 2026-10-05_fzr_not_a_code.py switched off: the FazerCards «gift
-- cards» that were never codes. Owner asked for a delete, not a hide.
--
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-10-05_fzr_not_a_code_purge.sql
--
-- Scope is pinned to the 2026-10-04 voucher import (created_at) and to rows
-- already inactive / hidden; anything an order references aborts the whole
-- transaction (order_items.sku_id is RESTRICT anyway — this just says so first).
begin;

do $$
declare n int;
begin
  select count(*) into n from order_items oi join skus s on s.id = oi.sku_id
   where s.created_at >= '2026-10-04 20:00+00' and not s.active;
  if n > 0 then raise exception 'inactive import SKUs are referenced by % order items', n; end if;
end $$;

-- 1. the switched-off fzr mappings on SKUs that stay on sale via another supplier
with gone as (
  delete from sku_supplier_mapping m using skus s
   where s.id = m.sku_id and m.supplier_slug = 'fzr' and not m.is_active
     and s.created_at >= '2026-10-04 20:00+00' returning 1)
select 'fzr mappings deleted', count(*) from gone;

-- 2. the inactive import SKUs (mappings, rules, prices, history cascade)
with gone as (
  delete from skus s using products p
   where p.id = s.product_id and p.kind = 'voucher' and not s.active
     and s.created_at >= '2026-10-04 20:00+00' returning 1)
select 'skus deleted', count(*) from gone;

-- 3. the hidden import brands with nothing left to sell: products, then brands
with empty as (
  select b.id from brands b
   where b.created_at >= '2026-10-04 20:00+00' and not b.visible_b2b
     and not exists (select 1 from products p join skus s on s.product_id = p.id where p.brand_id = b.id)
), gp as (
  delete from products p where p.brand_id in (select id from empty) returning 1)
select 'products deleted', count(*) from gp;

with gone as (
  delete from brands b
   where b.created_at >= '2026-10-04 20:00+00' and not b.visible_b2b
     and not exists (select 1 from products p where p.brand_id = b.id) returning slug)
select 'brands deleted', count(*), string_agg(slug, ', ' order by slug) from gone;

commit;
