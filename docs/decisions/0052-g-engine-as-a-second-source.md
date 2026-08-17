# 0052. G-Engine as a second source for game top-ups

- **Status**: Accepted
- **Date**: 2026-08-17
- **Deciders**: @jamaomonov
- **Tags**: fulfillment | integrations | sourcing

## Context and problem statement

Every game top-up we sell has exactly one route. When G2B is out of stock on a
denomination, or Waxpeer's wallet is short, the order parks in the fulfilment
inbox until an operator does something. A second supplier for the same titles
turns that from an incident into a fallback.

G-Engine (`api.g-engine.net`, v2.1) sells 37 recharge services, and the overlap
with our catalogue is close to exact: Mobile Legends (Russia **and** Global),
PUBG Mobile, Delta Force, Arena Breakout, plus Steam wallet in USD/RUB/KZT/UAH.

Prices are not uniformly better, which is the point — measured against our
current G2B cost on the same goods:

| SKU                            | G2B cost | G-Engine |
| ------------------------------ | -------- | -------- |
| Arena Breakout, ~66 bonds      | $0.775   | $0.887   |
| Mobile Legends RU, 35 diamonds | ~$0.62   | $0.602   |

So this is a **second source**, not a replacement. `sourcing` already routes a
SKU to a primary with an optional fallback; this gives that fallback something
to point at.

## Decision drivers

- A supplier outage should cost us margin, not the sale.
- The adapter must fit the existing `Fulfiller` protocol — the saga, the
  inbox, retry and the audit log are all built on it.
- A top-up cannot be un-bought. Whatever we do must not be able to pay twice.

## Decision outcome

Add `gengine` as a `Fulfiller` covering both halves of its catalogue:
`/recharge/*` for game top-ups and `/shop/*` for gift cards and keys.
Which one a SKU uses is decided by `sku_supplier_mapping.kind`
(`game` / `voucher`), exactly as the G2B adapter already branches.

### The order flow is a state machine, unlike our other adapters

A G-Engine order is created **unpaid**. G-Engine then verifies the player
account itself and only a `verified` order may be paid:

```
create ──► pending/processing ──► verified ──► pay ──► paid ──► shipped
                 │                    │
                 └──► invalid_account └──► cancelled
```

So `fulfill` usually returns `in_progress` and the existing poller drives the
rest through `check_status`. This is a feature, not friction: the supplier
catches a wrong player id _before_ our money moves, which is the same guarantee
the storefront's own check gives and a second net behind it.

`invalid_account` maps to a failed task with the customer's mistake named,
never to a generic supplier fault.

### Idempotency comes from a `uuid` we choose

The create call accepts a client-supplied `uuid`, and an order can be looked up
by it. A create whose response we lost is therefore recovered rather than
repeated — the one failure mode that would otherwise buy the same top-up twice.

### Mapping reuses `sku_supplier_mapping`

`external_product_id` holds the service id, `external_variant_id` the
denomination id. No new table, and the admin mapping screen already edits both.
The catalogue import wizard does not speak `/recharge/services` yet, so mappings
are entered by hand for now; the integrations page says so rather than offering
a sync button that would fail.

### Shop: reserve first, pay second — for a different reason

`/shop/*` sells activation codes (Xbox, Steam, Riot, PlayStation, Razer,
Nintendo, Apple, EA — 100+ products, each denomination reporting `stock`). Its
order flow is `pending → paid → shipped` with no verification step, because
there is no account to verify.

It also accepts **no client-supplied id**, so the `uuid` trick that makes the
recharge path safe is unavailable. The ordering carries that weight instead:
reserving costs nothing but stock, only paying spends. A create whose response
we lose therefore leaves an unpaid reservation, not a code we bought and cannot
find — and once the reservation exists we hold its id, so the poller can settle
a sale this call could not.

A `shipped` order with no codes yet stays `in_progress`. Handing a customer an
empty voucher is worse than making them wait, which is the rule the G2B adapter
already follows.

### Two response envelopes, one client

`/users/balance` and `/shop/*` wrap payloads in `{success, message, data}`;
`/recharge/*` returns the object bare. A refusal arrives as **HTTP 200 with
`success: false`**, so the status code alone never says whether a call worked.
Both quirks are handled once, in the client, and pinned by contract tests
against the shapes the live API actually returned.

## Positive consequences

- A failing primary route has somewhere to go.
- Steam gains a second source in USD, and gains RUB/KZT/UAH if we ever want
  them — Waxpeer offers only its own.
- The health probe needed no new code: the integrations route resolves through
  the fulfiller registry (ADR-less, see `integrations/routes.py`), so `gengine`
  appeared in the admin the moment it was registered.

## Negative consequences

- A third supplier's quirks to keep in mind, and its wallet to keep funded —
  **the account balance is $0.00 today**, so the adapter is wired but cannot
  fulfil anything until it is topped up.
- `/gifts/*` and `/skins/*` are untouched.
- Shop codes are delivered straight to the customer rather than stocked into
  the code warehouse, so `inventory` does not yet know about them.
- No cancel endpoint exists upstream, so a cancelled task cannot be withdrawn
  at the supplier; the adapter says so instead of pretending.

## Follow-ups

- Teach the catalogue wizard `/recharge/services` so mappings stop being manual.
- Feed shop `stock` into the availability sweep so a SKU stops being offered
  before a customer pays for something the supplier cannot hand over.
- Decide per-SKU which supplier is primary once both have real cost history.
