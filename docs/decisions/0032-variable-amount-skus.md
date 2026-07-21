# 0032. Variable-amount SKUs (Steam wallet top-ups via Waxpeer)

- **Status**: Accepted
- **Date**: 2026-07-20
- **Deciders**: @jamaomonov
- **Tags**: backend | catalog | orders | fulfillment | pricing

## Context and problem statement

The catalog has only ever sold fixed denominations: a SKU is "60 UC" or "325
UC" and `sku.price_usd` is the price. Steam wallet top-ups don't fit that
shape — the customer picks a dollar amount ($1–$300) and Waxpeer, the
supplier, tops up their Steam login for exactly that amount. This is the
first product where the price cannot be read off the SKU row; it has to be
computed at checkout from the customer's amount, a live FX rate, and our
margin.

Two things needed a decision beyond "how do we call Waxpeer": where the
customer's amount lives in the order model, and where the margin lives in
the price. Both have a cheap-looking wrong answer that this ADR rejects.

## Decision drivers

- `orders` already has a well-understood shape (`OrderItem.qty ×
sku.price_usd`, frozen at checkout) that every other module (payments,
  fulfillment, wallet, admin order history) assumes. A variable-amount
  product should stay an `OrderItem` on a normal `Order` — falling out of
  the order list, the refund flow, or the admin UI is not acceptable for a
  one-off product decision.
- AGENTS.md §9: money is `Decimal`, never a float, and the customer must
  never be shown a price the server didn't compute itself.
- The regional top-up market's convention is to advertise "0% comission"
  and fold the margin into the exchange rate — Steam top-up resellers
  compete on the rate they show, not on a separate fee line.
- An automatic FX rate with no sanity checking is a silent way to lose
  money: a rate that is off by 2× still parses as a valid `Decimal` and
  would otherwise flow straight into a customer-facing price.

## Considered options

1. **Amount on the order line, price computed at checkout** — add
   `variable_amount` / `min_amount_usd` / `max_amount_usd` /
   `rate_multiplier` to `Sku`; the checkout body carries `amount_usd`
   instead of relying on `qty`; `pricing.variable` computes the price from
   the amount, a guarded FX rate, and the SKU's multiplier.
2. **Amount as `qty`** — sell a "Steam $1" SKU and let the customer buy
   `qty = 37` of it for $37.
3. **A separate module outside `catalog`/`orders`** — a dedicated
   "top-up" flow with its own order-like aggregate.

## Decision outcome

**Chosen option:** Option 1. The amount is a first-class field on the order
line (`OrderItemIn.amount_usd`, validated and frozen into
`OrderItem.unit_price_usd`), and the margin lives inside the FX rate the
customer is shown, not as a separate percentage anywhere in the UI or the
schema.

### Why the amount is a field, not `qty`

`qty` already means something specific everywhere downstream: fulfillment
creates exactly one `FulfillmentTask` per `OrderItem` and would multiply the
Waxpeer request by `qty`, doubling the money moved for "qty=2" instead of
topping up once for a bigger amount. `_resolve_line_unit_price` in
`orders/service.py` rejects `qty != 1` on a variable-amount line outright —
quantity is meaningless once the customer can type any dollar figure; buying
more means entering a bigger amount, not a higher count.

The `qty`-as-denomination option (a "Steam $1" SKU, `qty = 37` for $37) was
rejected for the same reason the design spec calls out: it doesn't avoid a
migration (`qty` semantics still had to be re-verified everywhere `qty` is
read), it can't represent cents (top-up amounts are two-decimal dollars),
and it shows nonsense like "37 × Steam $1" in order history and the admin
UI — for no savings, since a separate pricing path would still be needed.

### Why not a separate module

A parallel top-up flow outside `catalog`/`orders` would duplicate order
creation, payment linkage, fulfillment routing, and order history for one
product family, and the purchase would fall out of the unified order list
admins and customers already rely on. `catalog.Sku` gaining four nullable
columns (enforced complete-or-absent by `ck_skus_variable_amount_complete`)
and `orders` gaining one validated field is a much smaller footprint than a
second order aggregate, and the next variable-amount product (PSN and
similar are anticipated) reuses the same fields with its own
`rate_multiplier` — no new module, no new migration shape.

### Why the margin lives in the rate, not a percentage

`pricing.variable.display_rate(market_rate, multiplier)` is the
customer-facing rate; `rate_multiplier` lives on the `Sku` row, not in
global settings, because the next variable-amount product will want its own
margin, changed from the admin UI without a deploy. The storefront shows
"1 $ = 14 025 сум" and no separate fee line — matching how this market
already prices top-ups, and avoiding a second number (a percentage) that
would have to be kept consistent with the rate on every screen. There is
deliberately no code path that derives or displays a percentage from the
multiplier.

### The FX trust gate is fail-closed

`pricing.fx_guard.guarded_usd_rate` sits between the `fx` module's rate
lookup and every price a variable-amount SKU shows or charges. If `fx`'s
entire provider chain is down (`FxUnavailableError`), `guarded_usd_rate`
raises `RateRejected("unavailable", ...)` itself, before a rate ever reaches
`check_rate` — a total FX outage, and the most operationally severe of the
five reject reasons. Otherwise `fx` already retries providers, caches, and
rejects non-positive numbers — what it cannot judge is a rate that parses
fine but is simply wrong (half the real value, or six hours stale).
`check_rate` then runs four further checks in this order — non-positive,
stale (`pricing_fx_max_age_seconds`), deviation from the last known-good
rate (`pricing_fx_max_deviation_pct`), and an absolute sanity band
(`pricing_fx_min_rate_uzs`…`pricing_fx_max_rate_uzs`) — and **any** failure
(including `unavailable`) raises `RateRejected`. `catalog.service._resolve_variable_price`
turns a rejection into a missing display price (never a fallback to the raw
market rate); `orders.service._variable_line_charge` turns it into a 502
(`UpstreamUnavailableError`) that blocks the order outright. Both call
sites log the rejection at error level (`pricing.rate_rejected`) so it
reaches whoever is watching. Failing closed costs a sale; failing open
would sell every order at whatever the bad rate implied until someone
noticed — the asymmetry is deliberate.

### Refunds on a Waxpeer `error` are manual, not automatic

When Waxpeer reports `status = "error"` on a top-up, it does **not** refund
our supplier balance (unlike `canceled`, which does). `WaxpeerFulfiller`
marks the task `failed` with a `last_error` that says so ("waxpeer reported
an error on this top-up; it does not auto-refund this case — needs manual
reconciliation"), and it surfaces in the admin Fulfilment Inbox's "Failed"
tab like any other automatic-supplier failure — that `last_error` text is
what an admin actually finds this task by. (`WaxpeerFulfiller` also builds
an `extra_metadata.needs_reconciliation = true` flag, but almost every
top-up's terminal outcome is discovered later by the reconciliation sweep
via `check_status`, whose `FulfillStatus` return type has no
`extra_metadata` field — and `fulfillment.process_webhook_update`, which the
sweep calls, never writes `task.extra_metadata`. So this flag is not a
reliable, queryable signal in production; `last_error` is. See the "Known
limitation" note in `docs/runbooks/waxpeer-troubleshooting.md`.) There is no
auto-refund of the order — refunding the customer is a manual admin action
(`POST /api/v1/admin/payments/{id}/refund`), the same path every other
supplier failure already uses. An automatic per-line refund was considered
and rejected: this codebase refunds whole orders, admin-triggered (see the
wallet/payments refund flow), and a multi-item order with one bad top-up
line would need either refunding the whole order for one line's failure or
a partial-refund
currency conversion the Waxpeer adapter has no reason to own. Automating
single-line refunds is a payments-module decision, not something to bolt
onto one supplier adapter. The admin's other job in this case — separate
from the customer refund — is opening a Waxpeer support ticket with the
top-up's pay id to recover _our_ side of the money, since Waxpeer kept it.

### Positive consequences

- Variable-amount purchases are ordinary orders: they appear in order
  history, the admin order list, and the fulfilment inbox without any
  special-casing beyond the checkout pricing path itself.
- The next variable-amount product (a different supplier, a different
  margin) reuses `Sku.variable_amount` / `min_amount_usd` /
  `max_amount_usd` / `rate_multiplier` and `pricing.variable` as-is.
- The FX trust gate is a single, reusable chokepoint — both the storefront
  price and the checkout price go through it, so a bad rate can't be shown
  and then charged differently.

### Negative consequences

- A rejected rate takes the whole variable-amount SKU off sale, not just
  slows it down — a wide swing in the real market rate (not just a bad
  provider read) could trip `pricing_fx_max_deviation_pct` and require an
  admin to look before the product comes back.
- The Waxpeer `error` path leaves money recovery to a human opening a
  support ticket; there is no automated reconciliation of _our_ balance
  with Waxpeer, only of the _order's_ status (see the reconciliation sweep
  in `apps/scheduler`).
- The structured reconciliation flags (`needs_reconciliation`,
  `supplier_refunded`, `give_amount_shortfall_units`) only reach
  `task.extra_metadata` for a task resolved inline through `fulfill()`.
  Since Waxpeer has no webhook, almost every task is instead resolved by
  the polling sweep's `check_status()`, whose `FulfillStatus` return type
  has no `extra_metadata` field — a known limitation, not a design choice.
  `last_error` and the `waxpeer.give_amount_short` log line are the
  reliable signals until `FulfillStatus` gains a metadata slot (a
  follow-up, not done here).

## Validation

`apps/api/tests/unit/test_variable_pricing.py` (rounding, gross-up, bounds),
`apps/api/tests/unit/test_fx_guard.py` + `test_fx_guard_db.py` (all five
reject reasons, decision ordering),
`apps/api/tests/contract/test_waxpeer_fulfiller.py` (status mapping,
idempotent replay, shortfall flagging),
`apps/api/tests/integration/test_waxpeer_reconcile.py` (sweep behaviour),
and the orders integration suite (checkout total for a variable-amount
line, amount outside SKU bounds rejected, client-sent price never
trusted).

## Alternatives considered (detail)

### Option 2 — amount as `qty`

Would need no schema migration, but every consumer of `qty` (fulfillment's
`× qty` gross-up logic, order-history line rendering, the admin SKU editor)
would need an exception for this one product family, and the two-decimal
requirement (`$9.99`) has no representation in an integer `qty`. Rejected —
see "Why the amount is a field, not `qty`" above.

### Option 3 — separate module

Full independence from `catalog`/`orders` at the cost of a second order
aggregate, duplicated payment linkage, and the purchase disappearing from
the unified order list. Rejected outright during brainstorming; see "Why
not a separate module" above.

## References

- `docs/superpowers/specs/2026-07-20-steam-topup-waxpeer-design.md` —
  feature design spec
- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — catalog
  three-level model, `required_fields`
- [ADR-0013](./0013-fulfillment-skeleton-and-provider-stubs.md) —
  `Fulfiller` protocol, saga FSM
- [ADR-0031](./0031-storefront-player-check.md) — the `waxpeer` branch of
  the storefront login/player-id check (Steam login validation reuses this)
- `apps/api/src/yupay/modules/catalog/models.py` — `Sku.variable_amount` /
  `min_amount_usd` / `max_amount_usd` / `rate_multiplier`
- `apps/api/migrations/versions/0025_variable_amount_skus.py`
- `apps/api/src/yupay/modules/pricing/` — `variable.py`, `fx_guard.py`
  (README in the same directory)
- `apps/api/src/yupay/modules/orders/service.py` —
  `_resolve_line_unit_price`, `_variable_line_charge` (checkout does **not**
  preflight the supplier balance — a paid order is never refused for the
  supplier being short; low balance is a soft failure at fulfilment, mirroring
  G2B)
- `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer.py`,
  `waxpeer_client.py`
- `apps/scheduler/src/yupay_scheduler/jobs/waxpeer_reconcile.py`
- `docs/runbooks/waxpeer-troubleshooting.md`
