# 0095. `brands.visible_retail`: a brand for resellers only

- **Status**: Accepted
- **Date**: 2026-10-04
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data

## Context and problem statement

The owner wants a brand that resellers can buy through `/merchant/v1` and the
cabinet while retail customers do not see it at all — no listing, no brand
page, no checkout.

ADR-0068 §4 said `active` already **is** retail visibility and put
`visible_b2b` beside it. Half of that held: the merchant catalogue ignores
`active`. But the merchant order path reuses retail's buyability rule
(`orders.sku_is_buyable`, called from `merchants.quote.load_orderable_sku`),
which requires `brand.active`. So `active=false` hid the brand from both
channels, and the catalogue even listed SKUs that every order then refused.
"Reseller-only" was not expressible.

## Decision drivers

- No change for any existing brand.
- One rule for buyability (maintenance, stock, the active chain) — a second
  copy for merchants would drift.
- A hidden brand must not be reachable by a known slug or SKU id either.

## Considered options

1. **`brands.visible_retail`**, default true; `active` stays the master switch.
2. **Make the merchant path ignore `active`**, so `active=false` + `visible_b2b`
   means reseller-only. Changes the meaning of every disabled brand on prod:
   anything switched off with `visible_b2b` still on would start selling to
   resellers the moment this shipped.
3. **A SKU-level flag.** Not what was asked; a brand-level switch is.

## Decision outcome

**Chosen option:** 1. Additive, defaults to the current behaviour, and keeps
`active` meaning "off everywhere".

Storefront gates read `active AND visible_retail`: every read in
`catalog/service.py`, the Merchant Center feed, the public player check, the
skins buy panel, `orders.quote_cart`, and `orders.create_order` for any actor
without a `merchant_id` (`orders.sku_is_retail_visible`). The merchant
catalogue, quote, validate and orders never read it. Admin edits it on the
brand form («Показывать клиентам»), through the plain brand `PATCH`.

### Positive consequences

- Reseller-only, retail-only, both and neither are all expressible.
- No backfill; migration 0094 is one column with a `true` default.

### Negative consequences

- Two flags to check when a brand "doesn't show": `active` and the channel's
  own gate.
- Brand reviews and blog brand links do not read the flag — the same as for
  `active` today.

## Validation

`tests/integration/test_brand_visible_retail.py`: storefront reads miss the
brand, retail checkout and cart quote refuse its SKU, the merchant quote
accepts it, the public player check 404s.
