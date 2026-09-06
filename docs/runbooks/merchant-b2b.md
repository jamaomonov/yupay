# Runbook — Merchant B2B catalog

## Post-deploy: verify the launch-flip (migration 0068)

`apps/api/migrations/versions/0068_catalog_b2b_flags.py` adds `visible_b2b`
to `brands`/`skus` and backfills it on deploy: every active brand of an
active, `top_up`/`voucher` SKU flips `visible_b2b = true`, except the
`steam-gifts` brand (a spec non-goal, excluded by slug).

**Do not trust the migration docstring's dev-snapshot list of brands as the
expected result on prod.** The flip runs against whatever the catalog holds
on deploy day — brands added, removed, or deactivated since this migration
was written change the outcome, and the docstring is a point-in-time example,
not a spec. Always verify against the live result:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT slug, visible_b2b FROM brands ORDER BY visible_b2b DESC, slug;"
```

Read the output against the actual rule, not a memorized list: every row
with `visible_b2b = t` should be an active brand carrying at least one
active `top_up`/`voucher` SKU, and `steam-gifts` should be the one
otherwise-eligible brand sitting at `f`. If a brand you expected to see
flipped isn't there, check whether it (or all of its SKUs) was inactive at
deploy time — the migration only flips what was active then; it does not
re-run when a brand is reactivated later (see "Reflipping a brand" below).

## Reflipping a brand after the fact

The 0068 backfill is a one-time migration, not a standing rule — a brand
activated (or given its first active SKU) after deploy does **not**
automatically gain `visible_b2b`. The admin UI covers per-brand/per-SKU
toggles and bulk **markup** (spec §8.3); what it does not yet offer is a bulk
**visibility** action — for that, flip by hand:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "UPDATE brands SET visible_b2b = true WHERE slug = '<brand-slug>';
   UPDATE skus SET visible_b2b = true
     FROM products
    WHERE skus.product_id = products.id
      AND products.brand_id = (SELECT id FROM brands WHERE slug = '<brand-slug>')
      AND skus.active AND products.active
      AND products.kind IN ('top_up', 'voucher');"
```
