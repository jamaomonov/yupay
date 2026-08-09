# 0049. Track supplier stock so gift cards cannot oversell

- **Status**: Accepted
- **Date**: 2026-08-10
- **Deciders**: @jamaomonov
- **Tags**: catalog | integrations | frontend

## Context and problem statement

Every product YuPay had sold until now was a game top-up: minted on demand by a
supplier API, infinite by construction. Nothing in the catalog modelled scarcity,
because nothing needed to.

Gift cards are different. They are real codes sitting in G2B's warehouse, and a
large share of its 12 837 voucher listings sit at zero at any moment. The count
also moves on its own — observed live, "800 Robux Global" went 423 → 422 between
two calls seconds apart, because every other reseller draws on the same pool.

Selling one we cannot deliver is not a failed request. The customer has paid, the
order cannot be fulfilled, and someone has to issue a refund by hand.

This landed alongside two other firsts: a second catalog category (`gift-cards`;
the storefront had shipped exactly one since launch), and the first products of
`kind="voucher"` — whose fulfilment path had been built long before and never had
a product to run on.

## Decision drivers

- A wrong sale here costs the whole amount plus manual work, not a margin.
- The supplier's count is authoritative and volatile; ours is always a snapshot.
- Whatever we show a customer becomes a promise. We do not control the pool.
- Games must not be affected. Any design that could accidentally mark a top-up
  unavailable is worse than the problem it solves.

## Considered options

1. **Reuse `Sku.active`** — flip it off when the supplier runs dry.
2. **Check stock live at checkout** — ask G2B during order creation.
3. **A nullable `supplier_stock` column**, refreshed on a schedule, with a
   derived boolean on the DTO and a guard at checkout.

## Decision outcome

**Chosen option: 3.**

Option 1 collapses two different facts into one flag. An operator hiding a SKU
and a supplier running out are unrelated, and the next refresh would silently
overwrite the operator's intent. Option 2 puts a third-party HTTP call on the
checkout path, which contradicts the standing rule against synchronous supplier
calls in request handlers (AGENTS.md §10) and fails the order when G2B is slow.

**The nullability is the semantics**, not an oversight:

| value  | meaning                                                        |
| ------ | -------------------------------------------------------------- |
| `NULL` | not tracked — every game top-up, and lines G2B reports as `-1` |
| `0`    | out of stock — do not sell                                     |
| `> 0`  | that many codes left at the supplier                           |

G2B answers `-1` on lines that are demonstrably sellable, so it is read as
silence rather than as a deficit. Guessing the other way would have quietly
pulled every unlimited line off the storefront — the more expensive mistake of
the two, and the one the unit tests pin.

**The count never reaches the customer.** `SkuOut` carries only the derived
`in_stock` boolean. "3 left" would be a promise about a number we do not own and
cannot honour once another reseller drains it.

**The guard is server-side.** `orders.service._sku_is_buyable` requires stock, so
a customer who presses Pay on a stale page is refused rather than charged. This
matters because brand pages are ISR at 300 s: a SKU that empties stays visible
for up to five minutes.

**Storefront treats absence as availability.** `in_stock` is honoured only when
explicitly `false`. The web build prerenders against the deployed API
(`web-ssg-prerenders-against-deployed-api`), so a build running before this field
shipped must not grey out the entire catalog.

**Refresh reads one product id at a time.** The paginated list is ~12 800 rows —
129 requests to find the ten mappings we have — against one request each via
`GET /products/{id}`. Runs on the price-refresh interval, each SKU in its own
transaction, alerting once on the transition into empty rather than every tick.

### Negative consequences

- Stock is a snapshot with a refresh interval plus a 300 s ISR window in front of
  it. Between sweeps the storefront can offer something already gone; the
  checkout guard is what makes that safe rather than expensive.
- A sold-out card is still rendered, dimmed. Filtering it out would be less code,
  but a denomination that vanishes between visits reads as a pricing change.
- Import scripts must remember to seed stock, since the first scheduler tick may
  be an hour out. `2026-08-10_gift_cards_import.py` reads it inline, which also
  proves each supplier id resolves before a mapping is written.

## Validation

- Unit tests pin `normalise_stock` (including `-1` → NULL and `bool` not being a
  count) and `Sku.in_stock`.
- An integration test empties a real SKU and asserts checkout returns 422, with a
  companion asserting NULL stock still sells — the same guard read backwards
  would refuse the whole catalog.
- A catalog-route test empties a row and asserts the DTO reports it, after the
  first cut shipped blind: `SkuOut` is built field by field rather than from the
  ORM object, so `in_stock` kept its default of `True` everywhere — present,
  plausible and always wrong.
- Sold-out rendering verified live in both surfaces: dimmed, disabled, labelled.

## References

- [ADR-0024](./0024-g2b-catalog-import.md) — the game import this deliberately does not reuse
- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — Brand/Product/SKU + form schema
- `scripts/seed/2026-08-10_gift_cards_import.py`, `scripts/seed/gift_cards_seo.sql`
