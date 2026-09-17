# Design: sourcing you can see, compare and switch in bulk

**Date:** 2026-09-18
**Status:** Approved in chat — scope and the pricing decision are the owner's, recorded in §2
**Branch:** `feat/sourcing-by-brand`
**Builds on:** ADR-0081 (NOVA as a reserve), ADR-0082 (Steam + a real cost basis)
**Surface:** API (`integrations.price_refresh`, `integrations.service`, `catalog.admin_service`, `sourcing`), scheduler, admin SPA
**New ADR:** 0083

---

## 1. Problem

Switching Free Fire to NOVA took a seed script, and the reason is the screen: sourcing edits **one
SKU at a time**. Nine SKUs meant nine cycles of pick-choose-save, so the work went to a script that
an operator cannot run. That is the visible half.

The invisible half is worse. **The screen cannot answer the question an operator is actually
asking** — who is cheaper for this SKU. Nothing in the admin compares suppliers, because nothing
collects the numbers: `integrations.service.refresh_sku_cost_for_mapping` refuses any supplier but
G2B in its first line, and `supplier_price_history` — a table that has carried a `supplier_slug`
column since it was created — holds 17,377 G2B rows and nothing else. The Free Fire decision was
made by reading NOVA's live catalogue by hand.

And the switch we just made left a third problem behind. Free Fire's nine SKUs now route to NOVA,
but their `Sku.cost_usdt` still tracks G2B, because that is the only supplier the hourly job knows.
So the margin the owner reads for those SKUs is computed against a supplier that no longer fills
them: cost $0.82 where we now pay $0.79. Understated, which is the safe direction to be wrong in,
but wrong — and it will stay wrong for every future switch.

## 2. Decisions taken by the owner

1. **All four convenience asks are in scope**: bulk switching, supplier price comparison, a rules
   table you can search, and a brand-scoped screen. The last two subsume each other — one screen,
   described in §6.
2. **When a SKU moves to a cheaper supplier, the retail price stays and we keep the saving.** Free
   Fire's margin becomes ~13 % rather than its price dropping ~3 %.

## 3. Cost per supplier, recorded for everyone

`refresh_sku_cost_for_mapping` stops being G2B-only and becomes supplier-dispatched. NOVA is the
second implementation: a mapping's `external_product_id` is their `category_id` and its
`external_variant_id` is the `offer_id`, so one `GET /topups/offers` answers every SKU of that
category — the fetch is cached per category for the run rather than repeated per SKU.

Every active mapping gets a `supplier_price_history` row on every refresh, whoever the supplier is.
That table is the comparison: it already has the shape, it has simply never been given the data.

**Steam is excluded.** A NOVA Steam mapping carries the `steam-topup` sentinel and no offer, and its
cost is a percentage of a face value the customer chooses rather than a catalogue number. There is
nothing to look up, and the Steam margin already reads what the supplier actually charged (ADR-0082
§4), which is strictly better than a catalogue price would be.

## 4. Which supplier's cost becomes _the_ cost

`Sku.cost_usdt` is not a fact about a supplier. It is **our** cost basis: retail price derives from
it, order lines freeze it at checkout, and the margin report subtracts it. So exactly one supplier
may write it — **the one the SKU actually routes to**, resolved through `sourcing.resolve_for_sku`.

Every other active mapping records history and touches nothing else. Without that rule, a SKU with
both a G2B and a NOVA mapping would have its cost — and therefore its retail price — flip between
two suppliers' numbers every hour, depending on which refreshed last. After today's switch, 22 SKUs
carry two active mappings, so this is not hypothetical.

## 5. A price that ratchets

Decision 2 in one sentence of code: the automatic path may **raise** `price_usd` and may not lower
it.

`catalog.admin_service.set_sku_cost_usdt` re-derives the price from `margin_percent` whenever the
cost moves. Left alone, syncing Free Fire's cost down to NOVA's $0.79 would drop the shelf price
from $0.90 to $0.87 — handing the customer exactly the saving the switch was made to capture. So the
function takes `allow_price_drop`, the hourly job passes `False`, and an operator editing a cost by
hand still passes `True`, because a person lowering a cost on purpose usually means it.

A cost **rise** still raises the price, which is the half of the behaviour that protects the margin
when a supplier gets more expensive. A drop widens the margin and says so: the existing price-move
alert gains one line naming the direction and, on a drop, that the price was deliberately left
alone.

**What this does to the nine Free Fire SKUs already switched:** their cost falls to NOVA's on the
next refresh, their price does not move, and the margin report starts telling the truth — about
13 % where it says 10 % today.

## 6. The screen

One brand-scoped screen replaces the one-SKU-at-a-time editor, which stays reachable for a single
edit.

**Pick a brand.** The table lists every active SKU of it, one row each:

| column             | what it answers                                                                                                                         |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| SKU + denomination | which product this is, without decoding a code                                                                                          |
| route now          | the live `resolve_for_sku` answer, and whether it comes from a rule or the default                                                      |
| per supplier       | for each supplier with an active mapping: the latest recorded cost, cheapest highlighted, no mapping shown as a gap rather than a blank |
| our price          | `price_usd`, and the margin it implies against the routed supplier                                                                      |

**Switching.** A row switches from its own control. Tick several and one action switches them
together — the same write the single editor does, applied per SKU, reported per SKU: a partial
failure names which SKUs moved and which did not, rather than failing the batch.

**A switch that cannot work is refused before it is offered**, not after: forcing a supplier with no
active mapping is already refused by `sourcing.set_rule`, and the screen knows the mappings, so the
option is disabled with the reason visible rather than enabled and rejected.

**The rules table** keeps its place below and gains what it needs to be searched: brand, product and
denomination beside the code, a text filter, and filters by supplier and mode.

## 7. Out of scope

G-Engine's cost sync (its catalogue endpoint differs enough to be its own task, and NOVA is what
this branch needs to compare against G2B); any change to what a customer sees beyond the prices
§5 deliberately leaves alone; automatic switching on price — the comparison informs a human, it does
not act.

## 8. Validation

- A SKU with two active mappings refreshes both into history and writes `Sku.cost_usdt` **only**
  from the routed one — the §4 rule, asserted directly.
- A cost drop through the automatic path leaves `price_usd` untouched; through the admin path it
  lowers it; a cost rise raises it on both.
- The brand overview returns one row per active SKU with its route and its per-supplier costs, in a
  bounded number of queries — an N+1 here would be a screen that times out on a 35-SKU brand.
- A bulk switch writes every SKU it reports as switched, and reports every one it did not.
- The player-check and reserve invariants from ADR-0081/0082 still hold: no screen may offer a
  reserve as an automatic route.
