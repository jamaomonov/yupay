# 0107. FoxReload: Steam top-ups in whole dollars, the rest to Waxpeer

- **Status**: Accepted
- **Date**: 2026-11-24
- **Deciders**: @jamaomonov
- **Tags**: backend | fulfillment | suppliers | scheduler

## Context and problem statement

FoxReload (public-api.foxreload.com) sells Steam wallet top-ups by login as product
«Steam Wallet 1 USD (Global)»: one unit is one dollar, at $0.9549 a unit on 2026-11-24,
1–175 units per item. That is below face value, where Waxpeer costs face value plus its fee.
But the unit is a whole dollar, and 24 % of our Steam orders in the 30 days to 2026-11-24
carried cents ($10.50), 2 of 947 were above $175.

## Considered options

1. **Split per line: whole dollars within the cap to FoxReload, everything else to an
   overflow supplier (Waxpeer)** — chosen.
2. Whole-dollar Steam only on the storefront — changes what customers can buy for a supplier's
   unit size.
3. FoxReload as a manual reserve only — leaves the cheaper channel idle.

## Decision outcome

Chosen option 1, because the customer sees nothing and every line goes to the cheapest
channel that can buy it exactly.

- Sourcing still decides the SKU: `force_supplier = foxreload` splits as below,
  `force_supplier = waxpeer` (or any other) sends everything there — the owner's "switch it all
  over" lever, unchanged.
- When a task is created, `fulfillment.service._overflow_route` sends a `foxreload` line that
  `foxreload.takes_line` refuses (cents, below/above `FOXRELOAD_STEAM_MIN_USD`/`MAX_USD`) to
  `FOXRELOAD_OVERFLOW_SUPPLIER` (`waxpeer` by default). Empty → the line stays and the adapter
  refuses it before any call, graded `RETURNED`.
- The product id lives in the SKU's `sku_supplier_mapping` row (`supplier_slug='foxreload'`,
  `kind='game'`, `external_product_id` = their product id), so it is re-pointable without a
  deploy, and the `force_supplier` guard (mapping required) holds.
- An order is create (unpaid) + pay. Their `idempotencyKey` is refused on reuse
  (`ORDER_ALREADY_EXISTS`), so a repeat looks the order up by key; `foxreload` is in
  `KEY_REPLAYS_DEAD_ORDER` for the same reason as `fzr`. A lost `pay` is finished by the
  `fulfillment.foxreload_reconcile` sweep (10 s, the panel vendors' due-check runner), which pays an order still unpaid.
- They refund a failed wholesale item on their own (`refunded`): graded `RETURNED`.

### Consequences

- Good: cheaper Steam for 3 of 4 orders, nothing changes for the buyer, one-click full switch.
- Bad: two suppliers to fund for Steam; the Steam login check stays on Waxpeer
  (FoxReload's `GET /api/steam/check-login` is 1 request/second and unused for now).
- Neutral: the `order.completed` webhook (`/api/v1/webhooks/foxreload`, HMAC over
  `"{t}." + body`, 5-minute tolerance) only marks the task due; the 10 s panel-style sweep reads
  the order. Failed/refunded orders send no event — the sweep finds them.

## Links

- Runbook: `docs/runbooks/foxreload.md`
- Adapter: `apps/api/src/yupay/modules/fulfillment/suppliers/foxreload.py`
