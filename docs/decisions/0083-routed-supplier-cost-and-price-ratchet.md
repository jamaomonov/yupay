# 0083. One supplier owns the cost, and the automatic price only ratchets up

- **Status**: Accepted
- **Date**: 2026-09-18
- **Deciders**: owner, Claude
- **Tags**: backend | data

## Context and problem statement

[ADR-0081](./0081-nova-reserve-supplier.md) made it possible for a top-up SKU to carry two
active supplier mappings at once, and [ADR-0082](./0082-nova-steam-and-real-cost-basis.md) made
it real: nine Free Fire SKUs kept their G2B mapping and gained a NOVA one on top, with
`force_supplier = nova` pointing orders at the new one. Neither ADR touched what a SKU's _cost_
does when it has two live suppliers, because until this branch nothing needed it to —
`refresh_sku_cost_for_mapping` refused every supplier but G2B in its first line, so there was
only ever one number to write. That refusal also meant `supplier_price_history` — a table that
has carried a `supplier_slug` column since it was created — held nothing but G2B rows: the design
spec for this branch counted 17,377 of them and zero from anywhere else. The Free Fire decision
itself was made by reading NOVA's live catalogue by hand, because the product had no way to show
a comparison.

And the switch left a live bug behind it. Free Fire's nine SKUs route to NOVA, but `Sku.cost_usdt`
kept tracking G2B — the only supplier the hourly job knew how to price — so the margin the owner
reads for those SKUs was computed against a supplier that no longer fills them.

This branch (`feat/sourcing-by-brand`) makes the cost refresh supplier-dispatched instead of
G2B-only, adds NOVA as its second implementation, and has to answer three questions that follow
directly from a SKU being allowed two suppliers at once: who writes `Sku.cost_usdt` when two
mappings disagree, what happens to the retail price when the winning number is lower than before,
and what every other mapping's refresh is even for if it can't write anything.

## Decision drivers

- `Sku.cost_usdt` is not a fact about a supplier — it is **our** cost basis. Retail price derives
  from it (`catalog.admin_service.set_sku_cost_usdt`), an order line freezes it at checkout
  ([ADR-0053](./0053-freeze-the-cost-a-line-was-bought-at.md)), and the margin report subtracts
  it. Two writers means two different truths landing on the same column, hours apart.
- A comparison screen is worthless if only one supplier's price ever reaches a queryable table —
  the whole point of §6 of the design spec is to answer "who is cheaper for this SKU" without an
  operator opening NOVA's dashboard by hand.
- The owner's decision on what a cheaper supplier is _for_: «оставить цену, забрать экономию» —
  leave the price, take the saving. A switch that finds a cheaper supplier should widen the
  margin, not hand the difference to the customer as a markdown nobody decided on.
- A cost **increase** is a different event from a cost decrease and must not get the same
  treatment: letting a rising supplier cost sit under an unmoved retail price would quietly eat
  the margin the ratchet exists to protect.

## Considered options

1. **Leave the refresh G2B-only.** Rejected — it was already wrong the moment a SKU could have a
   second live supplier, and it is why the Free Fire margin bug above exists at all.
2. **Let whichever mapping's refresh runs last write `Sku.cost_usdt`.** Rejected — see Decision 1;
   this is the option that makes 22 SKUs' retail prices nondeterministic.
3. **Exactly one supplier — the one the SKU is actually routed to — may write `Sku.cost_usdt`; every
   other active mapping records history and touches nothing else** (chosen).
4. **Let the automatic refresh re-derive `price_usd` from cost however the margin math comes out,
   same as a human editing a mapping does.** Rejected — see Decision 2; this is the option that
   handed Free Fire's NOVA saving to the customer.
5. **The automatic path may raise `price_usd` and may not lower it; a human editing a cost by hand
   still can** (chosen).
6. **Record price history only for the routed supplier**, since that is the only number that
   matters to the SKU. Rejected — see Decision 3; it reproduces the exact gap this branch exists
   to close, just with NOVA added to the refusal list instead of removed from it.
7. **Record history for every active mapping's refresh, whether or not it's routed** (chosen).

## Decision outcome

**Chosen option:** 3 + 5 + 7 together — one writer for the cost basis, a price that only ratchets
up on the automatic path, and history for every mapping regardless of who's routed.

### 1. Only the routed supplier writes `Sku.cost_usdt`

`cost_refresh.refresh_sku_cost_for_mapping` resolves the SKU's live route through
`sourcing.resolve_for_sku` and calls `_is_routed_supplier(decision, mapping.supplier_slug)` before
it will touch `Sku.cost_usdt`. That helper matches two shapes: a `top_up` SKU (or any SKU with an
explicit `force_supplier` rule) names its supplier directly as `decision.primary`; a `voucher` SKU
with no override routes to inventory first by kind-default, so the supplier that would actually be
charged on a stockout sits in `decision.fallback` instead, and that is the one whose refresh owns
the cost. Neither `force_inventory` nor `manual` matches any supplier, on purpose — no live
supplier price is "the" cost basis there.

**What breaks without it, concretely.** After the Free Fire switch, 22 SKUs carry two active
mappings — the number both the design spec and the shipped code's own module docstring
(`integrations/cost_refresh.py`) record. Every one of those SKUs has a `margin_percent` on file,
so a cost move re-derives `price_usd`. Without the routed-supplier rule, the hourly job (and the
on-demand admin trigger, which runs the identical code) would write whichever of G2B's or NOVA's
number it reached last on that pass — no ordering between suppliers is guaranteed run to run — and
those 22 SKUs' shelf prices would flip between two different numbers roughly every hour, for a
reason no operator chose and nothing announces. This is not hypothetical: it is exactly the bug
that would have shipped if this branch had stopped at "dispatch by supplier" and skipped this
rule.

The rule also caught a real bug during its own implementation, not a hypothetical one. An earlier
version of the routed branch wrote `Sku.cost_usdt`'s **old** value — the _other_ supplier's
number, on a SKU that had just been switched — into `previous_cost_usdt` on the history row,
recording a price move that had never actually happened into the very table this branch exists to
build. The fix (`0f0fbb51`) separated two questions that look like one: "did our cost move" (drives
`updated`, the alert, and whether a history row is written at all — about `Sku.cost_usdt`) from
"what did this supplier last cost" (the history row's own baseline — about that supplier, read
from its own last recorded row via `_last_history_cost`, never from `Sku.cost_usdt`). They agree
except exactly when a SKU has just been switched, which is precisely when getting it wrong would
matter.

### 2. The automatic path may raise `price_usd` and may not lower it

`catalog.admin_service.set_sku_cost_usdt` takes `allow_price_drop: bool = True`. The hourly
scheduler job and the on-demand admin trigger both run through the shared
`price_refresh.refresh_all_mappings`, and that is the one caller in the codebase that passes
`False`: a cost drop still updates `Sku.cost_usdt`, but the margin-derived candidate price is
written only if it is not lower than the SKU's current price. A cost **rise** still raises the
price under both flag values — that half is what stops a supplier getting more expensive from
silently eating the margin, and leaving it out would have been exactly as silent a bug as the one
this decision prevents.

This is the owner's call, not an engineering default: «оставить цену, забрать экономию». Free
Fire's nine switched SKUs are the case it was written for — syncing their cost down to NOVA's
number without the ratchet would have dropped the shelf price by the same 0.8–3.6 % NOVA turned
out to be cheaper by ([ADR-0082](./0082-nova-steam-and-real-cost-basis.md) §1), handing the
customer exactly the saving the switch was made to capture.

**The consequence worth recording, because it is a real loss the owner accepted rather than an
implementation detail.** `POST /admin/integrations/refresh-all-prices` — the admin's one-click
"resync every price now" button — calls `price_refresh.refresh_all_mappings` directly, the same
function the hourly job calls. It always did share that runner; what changed is that the runner
itself no longer lowers a price. So the button that used to be a genuine full resync, capable of
correcting a price in either direction, **can now only raise a price or leave it alone** — an
operator who presses it expecting a downward correction across many SKUs at once will not get one,
even if a dozen suppliers all got cheaper overnight. The only way left to pull a price down is
per-SKU, through the mapping-save route (`allow_price_drop=True`, the operator's own action) or a
direct cost edit — never in bulk, and never automatically. Nothing in this branch replaces that
capability; it is a deliberate, accepted gap, not an oversight, and it is recorded here so the next
person who wonders why "refresh all prices" stopped catching a price drop does not have to read the
diff to find out.

### 3. Every active mapping's refresh records history, whichever supplier is routed

`refresh_sku_cost_for_mapping` writes a `supplier_price_history` row for **every** mapping it
refreshes, routed or not — the routed branch and the non-routed branch each call the same insert,
differing only in whose baseline they compare against
(`cost_update.previous_cost` for the routed supplier, that supplier's own last recorded price via
`_last_history_cost` for everyone else). This is what turns
`GET /admin/sourcing/brands/{brand_slug}` from a routing screen into a comparison one: it is the
only table in the system that ever held NOVA's price next to G2B's for the same SKU, and before
this branch it held nothing but G2B, because nothing else was ever allowed to write to it.

A row is written only when the price actually moved since that supplier's own last recorded value
— **on a change, not on every tick**. The design spec estimated the alternative (a row per mapping
on every hourly pass) at roughly 4,800 no-op rows a day against the ~220 mappings active before
this branch (a number close enough to today's real count to trust the order of magnitude), just to
say nothing had happened. The cost of keeping it change-only: a recorded price carries the date it
was _captured_, not the date it was last _checked_, so a three-week-old number and today's number
look identical on the comparison screen unless an operator reads `captured_at` beside it.

### Positive consequences

- The Free Fire margin bug this branch was written to close is actually closed: those nine SKUs'
  cost now reads from NOVA, the only supplier they route to, instead of from G2B, which no longer
  fills them.
- `GET /admin/sourcing/brands/{brand_slug}` can show a real per-supplier cost comparison for any
  brand with more than one mapped supplier, because the data now exists to compare — the Free Fire
  decision that used to require reading NOVA's catalogue by hand is now a screen.
- The routed-supplier rule generalises past NOVA: any future second source for an existing SKU
  gets the same protection without further code changes, because the check is against
  `sourcing.resolve_for_sku`'s answer, not against a supplier's name.

### Negative consequences

- **The admin's "refresh all prices" button no longer lowers any price**, as Decision 2 describes.
  An operator has to know the per-SKU path exists and use it deliberately for a downward
  correction; nothing in the UI currently says the bulk button stopped doing this.
- A voucher SKU with two active mappings and no explicit sourcing rule depends on
  `_is_routed_supplier`'s inventory-fallback clause to find its cost owner — the supplier that
  would actually be charged on a stockout, read from `decision.fallback` rather than
  `decision.primary`. That is one more shape the routing rule has to get right, verified by
  `test_cost_sync_voucher_uses_cache_unit_price`, but it is still a second code path inside a
  function whose job is "pick exactly one writer."
- `supplier_price_history` now grows for suppliers nobody has switched to yet — every reserve
  mapping (NOVA on Mobile Legends, PUBG) accumulates comparison data whether or not anyone reads
  it, which is the point, but it is more rows written for no immediate operational reason.

## Validation

- **Integration** (`apps/api/tests/integration/test_integrations_price_refresh.py`,
  `test_integrations_cost_sync.py`): a SKU with two active mappings (`g2b`, `nova`) writes
  `Sku.cost_usdt` and a history row when the **routed** supplier is refreshed; refreshing the
  **other** one writes only a history row and leaves `Sku.cost_usdt` at its prior value, asserted
  against the old value directly rather than merely "not the new one"; both histories are
  queryable afterwards and carry the right `supplier_slug`; a NOVA Steam mapping
  (`NOVA_STEAM_SENTINEL`) is skipped with a reason and writes nothing at all; a voucher SKU in
  `auto` with two mappings resolves its cost owner through the inventory-fallback clause; a
  `force_inventory` SKU's cost is left to nobody, matching the zero such rules found in production
  at the time.
- **Integration** (`apps/api/tests/integration/test_sku_cost_margin.py`): a cost drop with
  `allow_price_drop=False` leaves `price_usd` byte-identical while `cost_usdt` still moves; the
  same drop with `allow_price_drop=True` lowers the price as before; a cost rise raises the price
  under both flags; a SKU with no `margin_percent` is untouched either way.
- **Integration** (`apps/api/tests/integration/test_sourcing_brand_overview_routes.py`): one row
  per active SKU with its live route and per-supplier costs, the latest history row winning when
  several exist, and the response bounded at five queries regardless of SKU count
  (`MAX_BRAND_OVERVIEW_SKUS`, 500).
- **Integration** (`apps/api/tests/integration/test_sourcing_bulk_rules_routes.py`): a bulk switch
  writes every SKU it reports as switched and reports every one it did not, by name; the reserve
  guard from ADR-0081 survives the bulk path exactly as it does the single-SKU one.
- No test asserts a specific production row count or margin percentage — those numbers move with
  the catalogue and are recorded in the design spec and the runbook as measurements, not as
  invariants a test should pin.

## References

- [ADR-0081](./0081-nova-reserve-supplier.md) — the reserve pattern and `RESERVE_SUPPLIERS`; the
  first ADR to make two active mappings on one SKU a real, not hypothetical, shape.
- [ADR-0082](./0082-nova-steam-and-real-cost-basis.md) — the Free Fire switch that turned the
  cost-ownership question from theoretical to a live production bug, and the 0.8–3.6 % per-SKU
  NOVA discount Decision 2 above references.
- [ADR-0053](./0053-freeze-the-cost-a-line-was-bought-at.md) — why `Sku.cost_usdt` freezing onto an
  order line is the reason a silently-flipping cost basis is not a cosmetic bug.
- Design: `docs/superpowers/specs/2026-09-18-sourcing-by-brand-design.md`.
- Plan: `docs/superpowers/plans/2026-09-18-sourcing-by-brand.md`.
- Runbook: [`docs/runbooks/nova.md`](../runbooks/nova.md) — the Free Fire section this ADR's
  Decision 1 and 2 change the operator-visible behaviour of.
