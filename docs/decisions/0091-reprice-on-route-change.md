# 0091. Changing a route re-prices the SKU, in the same request

- Status: accepted
- Date: 2026-09-22
- Deciders: owner, engineering
- Supersedes: nothing. Extends [ADR-0083](./0083-routed-supplier-cost-and-price-ratchet.md)

## Context and problem statement

ADR-0083 settled **who** may write `Sku.cost_usdt`: only the supplier the SKU
actually routes to. It said nothing about **when**, and the gap showed.

`sourcing.set_rule` wrote the rule row and nothing else. So switching a SKU
from G2B to NOVA changed who was allowed to write the cost without changing
the cost: the column kept G2B's number, G2B had just lost the right to update
it, and NOVA had not yet used it. Everything derived from that column —
`price_usd` through `margin_percent`, per-merchant B2B markup, the sourcing
screen's "current" figure, the margin report — read a number belonging to a
supplier we had stopped buying from.

The window is `price_refresh_interval_minutes` (60) in the ordinary case. It
is **unbounded** when the new route is a supplier with no automatic price
collection (`waxpeer`, `manual`, `force_inventory`): nothing will ever write
that column again, and ADR-0083 already records that shape as reachable
"the day someone routes a SKU onto an unpriced supplier". This is that day's
mechanism.

The asymmetry was the tell. Saving a **mapping** in Integrations re-prices
immediately (`integrations.routes._refresh_sku_cost`). Saving a **rule** in
Sourcing did not. Two adjacent operator actions, both about where a SKU's
money comes from, behaving differently, with nothing anywhere saying so.

## Decision drivers

- An operator who switches a route has made a decision about cost; the system
  should agree with them before they navigate away, not an hour later.
- A switch is usually made _because_ the new supplier is cheaper. The saving
  belongs to us, not to the shelf price.
- A switch onto a dearer supplier must not leave us selling below cost.
- The rule change is the operator's actual intent; a supplier that will not
  answer must not be able to undo it.

## Decision outcome

`PUT /admin/sourcing/rules/{sku_id}` and `PUT /admin/sourcing/rules:bulk` call
`integrations.cost_refresh.refresh_routed_cost` after the rule is written, and
return the outcome as `cost_sync` on the response.

### 1. `allow_price_drop=False`, unlike the on-save mapping refresh

The one genuinely contestable choice, and the owner's call.

Choosing a route is choosing **where we buy**, not **what we charge**. A
cheaper supplier therefore widens the margin and leaves `price_usd` exactly
where it was — «оставить цену, забрать экономию», the same rule the hourly job
follows. A dearer supplier re-derives the price from the new cost and the
SKU's own `margin_percent`, because the alternative is selling below cost
until the next tick.

Saving a mapping keeps `allow_price_drop=True` and that stays correct: there
the operator is editing the mapping itself — pointing it at a different
denomination — so the new figure is a correction, and the price follows it.

### 2. Best-effort, and the reason travels back

A supplier that will not answer, a catalogue nobody has synced, an unpriced
route — none of these fail the request. The rule is already written, and a 5xx
there would leave the operator unsure whether the route moved at all. The
outcome comes back in `cost_sync.reason` instead.

An unpriced route deliberately leaves the stale cost in place rather than
blanking it. A NULL `cost_usdt` breaks margin and every B2B price derived from
it; a stale number with a visible warning is the smaller harm.

### 3. No Telegram alert

The hourly job alerts on threshold-crossing cost moves because they are
_unexpected_. A move an operator caused by pressing a button is not, and the
response on their screen is the feedback. The on-save mapping refresh made the
same call.

### 4. Bulk re-prices only the SKUs whose rule actually landed

A bulk switch already reports per-SKU success. A SKU whose rule write failed
routed nothing, so a cost move reported against it would be a fabrication;
those carry `cost_sync: null`.

### Positive consequences

- The sourcing screen agrees with reality the moment the operator leaves it.
- Routing a SKU onto an unpriced supplier now announces itself instead of
  freezing the cost silently — ADR-0083's documented-but-invisible shape.
- One shared helper, so the hourly job, the mapping save and the route change
  all go through the same `refresh_sku_cost_for_mapping`.

### Negative consequences

- The rule endpoints now make a supplier call (or a cache read) inside the
  request. They are admin-only, operator-triggered and off the order path —
  the same carve-out AGENTS.md §10 already grants the catalogue-sync routes.
- A bulk switch of 100 SKUs makes up to 100 of those. Acceptable at the cap
  the endpoint already enforces; a larger selection was already required to
  chunk itself.
- `cost_sync` is a new field on two response DTOs. Nullable, so a client that
  ignores it is unaffected.

## Validation

`apps/api/tests/integration/test_sourcing_reprice_on_switch.py`: a cheaper
supplier moves the cost and leaves the price (`price_drop_blocked`), a dearer
one raises the price off the new cost, an unpriced supplier reports a reason
and changes nothing, an unsynced catalogue still switches the route, and a
bulk switch re-prices exactly the SKUs it wrote.

## References

- [ADR-0083](./0083-routed-supplier-cost-and-price-ratchet.md) — who owns the
  cost, and the ratchet this reuses
- [ADR-0081](./0081-nova-reserve-supplier.md) — why a reserve supplier is only
  ever reached by an explicit rule, which is what makes this path common
