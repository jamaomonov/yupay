# 0093. CS2 skins: our own catalogue, Waxpeer listings, delivery to the customer's trade link

- **Status**: Accepted
- **Date**: 2026-09-28
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | payments

## Context and problem statement

We want to sell CS2 skins. Waxpeer — already our supplier for Steam wallet top-ups — sells
~1.19 million listings by API and delivers them as a Steam trade offer to any trade link. A skin
breaks four assumptions the rest of the catalogue and fulfilment stack rest on: a listing is one
physical item that someone else can buy first; delivery needs an action from the customer
(accepting a trade offer); a trade can sit in a Steam hold for days and roll back after we
called it a sale; and a rollback that is the buyer's fault charges the buyer — us — a 30 %
penalty and marks an account that Waxpeer can suspend from P2P buying.

Separately, the catalogue question: Waxpeer offers per-name aggregates with its own image CDN
(`images.waxpeer.com`), which would tell any customer who looks at an image URL where we buy.

The full design, with the live measurements behind every number, is
`docs/superpowers/specs/2026-09-28-cs2-skins-design.md`.

## Decision drivers

- The customer must accept a trade offer in Steam in every conceivable model; the design has
  to make that step succeed, because its failure is what we pay for.
- 94 % of listings are `auto` (automated delivery); the remaining 6 % are human sellers with
  phones and hours-long delivery. Offering them would define our delivery time by our slowest
  seller.
- Every catalogue read must be ours: 24 000 names, filters, search and facets cannot be a proxy
  over a supplier API that limits search to 20 requests a minute.
- Nothing that reaches the browser may identify the supplier.
- A trade-lock hold ("8-day cancellation") is avoidable before payment: it only happens to
  accounts without a 7-day-old mobile authenticator, and Steam will tell us so for a trade link.

## Considered options

1. **Deliver through our own Steam bot account** — buy to our inventory, accept, re-send to the
   customer; optionally pre-buy stock.
2. **Deliver straight to the customer's trade link**, buying as soon as the order is paid.
3. **Catalogue = Waxpeer's `/v1/prices` aggregate** with Waxpeer's images (the shape the
   `skinmarket` pet project used).
4. **Catalogue = an independent item database** (ByMykel/CSGO-API, MIT, from the game files,
   Steam-CDN images), with Waxpeer supplying listings only, joined by market hash name.
5. **Real-time listing mirror** over Waxpeer's Socket.IO price feed, one DB write per event.
6. **Five-minute snapshot aggregation** into one row per name.

## Decision outcome

**Chosen: 2, 4 and 6.**

- **2, because a bot buys nothing and costs a lot.** CS2 locks items received by trade for
  7 days, so a bot cannot resell what it just received; the customer still has to accept an
  offer; and the bot account carries every Steam risk. The purchase goes out at payment. An
  earlier draft waited for a «Я готов принять обмен» tap to cut "Buyer failed to accept"
  rollbacks; the 2026-09-28 spike showed a declined or unaccepted offer is refunded by Waxpeer in
  full with no penalty, and the owner dropped the gate the same day — a buyer who just paid is
  at the keyboard anyway, and the offer waits 30 minutes. Only `auto` listings are ever offered;
  hold listings never.
- **4, because 96.1 % of Waxpeer's names match ByMykel directly and 100 % of what we sell
  after normalising Doppler phases out of Waxpeer's names**, and because its images are Steam's
  own CDN — the host the customer's inventory already loads from. Item names stay English;
  categories, weapons and wear get RU/EN/UZ labels from a table we own.
- **6, because the CSV snapshot streams and aggregates in 9.3 s** and is the documented source
  of `auto`; it folds 1.19 M rows into 24 000, and it corrects the 7.6 % of names whose
  cheapest listing is a manual seller — which `/v1/prices` alone cannot see. Option 5 was
  rejected: with a 5-minute snapshot and a live `check-availability` at checkout, a real-time
  mirror adds load and no correctness.

Tracking follows the existing `waxpeer` supplier's shape: Socket.IO is a nudge, polling is the
truth, `status 5` is the only success, `6` returns the money through the existing refund path,
`penalties` are alerted as money spent. The full status contract is in the spec, §6.

### Positive consequences

- Catalogue reads never touch the supplier; the item-page listings read is the single §10
  carve-out and degrades to snapshot data when rate-limited.
- No supplier identity in image URLs, ids or names.
- Reuses the `waxpeer` balance, adapter, low-balance stall and reconcile sweep.

### Negative consequences

- A second daily-updated third-party dataset (ByMykel) becomes a dependency; a brand-new item
  is a stub row for up to a day.
- An offer the customer does not accept within Waxpeer's 30-minute window comes back as a
  refund (status 6), which our side must turn into a customer refund.
- Search is limited to 20/min until Waxpeer grants partner status; the item page has a
  token bucket and a fallback for that.

## Validation

- Plan 1 (catalogue): every `GET /skins/*` read except `/listings` answers from Postgres/Redis
  in an integration test with Waxpeer mocked out entirely; the snapshot job completes a real
  tick under 30 s on the VPS.
- Plan 3 (purchase): the spike's one real purchase confirms timings, the Socket.IO event and
  hold behaviour before the fulfiller lands; after launch, the share of orders ending in `6`
  with `reason = "Buyer failed to accept"` stays under 2 %.

## Alternatives considered (detail)

### Option 1 — own Steam bot

Pros: decoupled from seller timing, could pre-stock. Cons: 7-day trade cooldown on everything
received, capital in inventory, Steam account risk, the customer's accept step remains.

### Option 3 — Waxpeer aggregate as catalogue

Pros: one call, no second dataset. Cons: Waxpeer image CDN visible to customers; `min` includes
manual sellers (wrong for 7.6 % of names); no phase, float range, or weapon taxonomy.

### Option 5 — Socket.IO mirror

Pros: second-level freshness. Cons: a long-lived process with a DB write per market event for a
freshness the checkout re-check already provides.

## References

- [ADR-0066](./0066-steam-gifts-live-catalog.md) — dynamic checkout, adopt-don't-rebuy
- [ADR-0064](./0064-postgres-fulfilment-queue.md) — work reaches the worker as rows
- Waxpeer API docs: https://docs.waxpeer.com/ (llms.txt, statuses, socketio)
- ByMykel/CSGO-API: https://github.com/ByMykel/CSGO-API

## Amendment 2026-09-29 — the trade-link check (plan 3a)

`POST /skins/tradelink/check` calls Waxpeer `check-tradelink` and Steam
`IEconService/GetTradeHoldDurations` from its handler. It clears ADR-0031's conditions:
advisory (an outage answers `unavailable` and checkout goes on), off the order, payment and
fulfilment path, 4 s timeouts, a 10-minute Redis cache keyed by a hash of the link, a
60-second breaker, and its own `ip_guard` bucket. It is `POST` so the link — whose token lets
anyone send that account offers — stays out of the edge access log, and it writes nothing, so
it takes no `Idempotency-Key`. Listed in AGENTS.md §9 and §10.

## Amendment 2026-09-29 — money when a purchase falls through

A skin task that fails with `MoneyOutcome.RETURNED` (no substitute listing, or an offer the
customer declined or let expire — Waxpeer refunds those in full, spike §8.1) refunds the order
to the customer's YuPay balance automatically (owner, 2026-09-28): `fulfillment.service`
calls `payments.service.refund_order_to_wallet` from the same post-savepoint seam every
terminal failure passes. `UNKNOWN` and `SPENT` keep the alert-and-a-human path. A card
refund stays a support action. Skins therefore require a signed-in customer.
