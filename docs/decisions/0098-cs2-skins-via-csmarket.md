# 0098. CS2 skins bought through the csmarket public API

- **Status**: Accepted
- **Date**: 2026-10-09
- **Deciders**: @jamaomonov
- **Tags**: backend | data | payments

## Context and problem statement

YuPay sells CS2 skins (ADR-0093) with Waxpeer as the only source: a five-minute CSV
snapshot for the catalogue, live search for an item's offers, `buy-one-p2p` for the
purchase, `check-tradelink` for the buyer's link. csmarket.uz, the owner's second business,
buys the same skins through Skinslink and LIS-SKINS, which carry Waxpeer's sellers too and
are cheaper per item (measured 2026-10-07: blend −1.6 % against Skinslink alone, Skinslink
−1.4 % against Waxpeer). csmarket now exposes a public purchase API
(`docs/api/public-v1.md` in that repo) with a `cost` tariff: the offer's cost with no
csmarket markup, paid from a USD wallet. The owner's decision: YuPay buys through it and
Waxpeer is switched off for skins.

## Decision drivers

- One buying stack for both businesses; YuPay keeps its own margin, csmarket earns nothing
  on YuPay (owner, 2026-10-09: the seller sets the markup).
- No storefront rewrite: the web and mini app already speak `listing_id: number`.
- Reversible: Waxpeer stays wired and can be switched back without a deploy.
- The money rules of ADR-0093 hold: a skin that may have been delivered is never refunded
  automatically; an outcome is decided by the supplier's answer, never by a timer.

## Considered options

1. **csmarket public API as a supplier** — one adapter, csmarket does the sourcing.
2. **Port the Skinslink and LIS-SKINS clients into YuPay** — same prices, two adapters,
   the code maintained in two repositories.
3. **Stay on Waxpeer.**

## Decision outcome

**Chosen option:** 1. Option 2 duplicates two supplier integrations that csmarket already
runs in production; option 3 leaves ~2 % of cost and ~200 items on the table.

Shape of the integration:

- **Source switch.** `CS2_SKINS_SOURCE=waxpeer|csmarket` (default `waxpeer`) picks the
  catalogue job, the live-offer read, the trade-link check and the fulfiller for new
  orders. An order already placed keeps its supplier: `skin_trades.supplier` records it.
- **Catalogue.** The csmarket feed (`GET /catalog`, 1000 items a page, ~15 000 items,
  ~6 s a pass) replaces the Waxpeer snapshot in `skins.prices`. Items match on
  `(market_hash_name, phase)`; the phase comes from the feed slug, which csmarket builds
  with the same `slug_for` as ours. `price_usd` on the `cost` tariff becomes
  `min_auto_units`; `stock` becomes `count_auto`. The feed has no Steam price and no item
  type: the last known `steam_price_units` is kept, and a stub's category stays unknown
  until the daily ByMykel import fills it.
- **Offers.** `GET /catalog/{item_id}/offers` replaces Waxpeer search for an item page and
  checkout. csmarket's `offer_id` is an opaque string; the storefront keeps its numeric
  `listing_id`, derived as a stable 52-bit hash of `offer_id` (safe in JavaScript), and the
  real `offer_id` travels in the order line's `fulfillment_data`.
- **Purchase.** `POST /orders` with `client_order_id` = our fulfilment idempotency key,
  `offer_id`, `max_price_usd` = the cost we priced against, the buyer's trade link. A
  repeat with the same key answers 409 with the existing order, so a lost answer is
  settled by asking again, never by a second buy. **No substitute lot** (amended
  2026-10-10, csmarket's ADR-0013): a buyer picks a lot by float and stickers, so
  `offer_gone` / `price_above_max` return the money at once, and a line without an
  `offer_id` is never bought. `402 insufficient_balance` is handled like Waxpeer's low
  balance: refund to the buyer's balance and an ops alert. `409 trade_link_rejected`
  refunds and asks the buyer for a new trade link; `409 buying_disabled` refunds and asks
  them to try again in a few minutes (2026-10-17).
- **Lot check before payment** (amended 2026-10-10). The offers list trails the market by
  minutes (csmarket rebuilds LIS-SKINS lots from a five-minute export), and the cheapest
  lots of a popular skin sell inside that window: one buyer paid and was refunded four times
  in an evening. `POST /orders` now asks csmarket's
  `GET /catalog/{item}/offers/{offer}` (`skins.offer_check`) before the order exists — at
  the top of the route, after ending its one read, so no pool connection waits on it. Sold →
  `listing_gone` with the next lot, and the sold lot is hidden from the list for six
  minutes; cheaper → billed at the new price; dearer past 2 % → the buyer confirms the new
  price; no answer → the list price (the purchase checks again). A purchase that finds
  the lot sold (`offer_gone`, or a refund for `sold_out`) hides it for the same six minutes
  (amended 2026-10-17): csmarket checks Skinslink lots against a copy up to 30 s old, so a
  lot sold seconds earlier can pass the check. `price_above_max` is not a sale: it only
  drops the cached list so the page shows the new price.
- **Status.** `GET /orders/{order_id}`: `buying` in progress, `trade_sent` offer out,
  `delivered` succeeded, `refunded` returned with csmarket's reason. A rollback after
  delivery is not reported by csmarket (it stays `delivered`), so the Waxpeer-only
  protection watch and nightly audit skip csmarket trades.
- **Trade link.** `POST /tradelink/check` replaces Waxpeer's check (csmarket runs Waxpeer +
  Steam behind it).

### Positive consequences

- Cheaper cost per skin; one funded wallet for skins instead of Waxpeer's shared balance
  (which Steam top-ups also draw on).
- No storefront change.

### Negative consequences

- A second hop: an outage at csmarket stops skin sales at YuPay.
- ~1 500 items YuPay lists today are Waxpeer-only and disappear from the catalogue
  (measured 2026-10-09: 14 918 shared, 1 535 YuPay-only, 206 csmarket-only).
- No Steam price in the feed: the Steam cap works on the last value Waxpeer gave.
- Rollbacks after delivery become invisible to YuPay.

## Validation

- A real purchase on prod through csmarket reaches `delivered` and its cost matches the
  `cost` tariff.
- The catalogue job keeps ≥ 90 % of the items active that Waxpeer kept.
- Switching `CS2_SKINS_SOURCE` back to `waxpeer` restores the old behaviour with no deploy.
