# 0105. The automatic price follows a cost drop past a 2 pp tolerance

- **Status**: Accepted — amends the ratchet half of [ADR-0083](./0083-routed-supplier-cost-and-price-ratchet.md)
- **Date**: 2026-11-13
- **Deciders**: owner, Claude
- **Tags**: backend | pricing

## Context

ADR-0083 made the automatic price path a ratchet: a cost rise raised `price_usd`, a cost drop
only widened the margin («оставить цену, забрать экономию»). Two months later the owner opened
`mlbb-9994`: the margin field read 10%, the cost was $116.58, the price $144.22 — 23.7% in fact,
parked there by an October peak cost of $131.10. On prod 3,308 of 10,677 active SKUs with a margin
were more than 2 pp over target, 1,138 more than 5 pp. The owner's rule now: least manual control,
never below cost, never overpriced.

## Decision

`set_sku_cost_usdt(allow_price_drop=False)` — the hourly refresh, the «обновить все цены» button,
a sourcing route switch — writes a lower margin-derived price once the current price sits more
than `PRICE_DROP_TOLERANCE_PP` (default 2) percentage points above the target margin, whether or
not the cost moved this tick. Within the tolerance a drop is still banked, so cent-level supplier
wobble does not move shelf prices hourly. A cut deeper than `PRICE_DROP_MAX_AUTO_PCT` (25%)
is not made automatically: on prod those were mis-mapped variants (a $78.76 pack over a $0.68
cost) and Roblox priced far over its cost, where following the cost would sell below the real
one — they stay for the margin-drift digest and a person. Rises pass through as before. A negative setting
restores the ratchet.

The admin SKU form shows «По факту N%» under the margin field whenever the saved price is half a
point or more off target.

## Consequences

- The first hourly pass after deploy lowers the parked backlog (every SKU whose routed supplier
  answers). Those price moves are not in the price-change digest, which counts cost moves.
- Margin banked on cheaper suppliers is given back to customers beyond 2 pp.
- The margin-drift digest now lists only SKUs the refresh does not reach (no price-collecting
  mapping, hand-set prices).

## Amendment, 2026-11-14 (security audit)

The cap guarded retail only: `cost_usdt` itself was still written, and the reseller price
(`merchants/pricing.py`, cost × (1 + markup)) follows it with no margin guard — so a supplier
glitch or a mis-mapped variant could make wholesale stock buyable far below cost before
anyone looked. The hourly sync now **holds** a cost more than `PRICE_DROP_MAX_AUTO_PCT` below
the one on file: nothing is written, and a «🛑 Закупка упала слишком резко» digest (each SKU
once a day) asks a person to confirm by saving the mapping, which writes any value.
