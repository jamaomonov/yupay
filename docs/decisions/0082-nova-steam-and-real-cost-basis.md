# 0082. NOVA's Steam reserve, a real cost basis for margin, and switching Free Fire CIS

- **Status**: Accepted
- **Date**: 2026-09-17
- **Deciders**: owner, Claude
- **Tags**: backend | data | payments

## Context and problem statement

[ADR-0081](./0081-nova-reserve-supplier.md) wired NOVA up as a reserve fulfilment supplier and
a player-check fallback. The day after that merged, looking at NOVA's live prices against our
own catalogue turned up three more things, all in the same supplier:

1. **Free Fire CIS is cheaper at NOVA on every SKU we sell it** — 0.8–3.6% below our incumbent,
   measured 2026-09-17 against live `cost_usdt` (design doc §1's table).
2. **NOVA sells ten Free Fire items we don't** — six Level Up Packages, three Evo Access
   durations, a Newbie Bundle — all in the `free_fire_cis` category, none in G2B's.
3. **NOVA's Steam top-up is charged at a plan discount**: $10 of wallet costs us $9.80. Waxpeer
   and G-Engine both charge face value, and `margin_usd_expr`'s variable-amount branch assumed
   they always would — `qty × unit_price_usd × (multiplier − 1)` treats a dollar of wallet as
   costing a dollar. Left alone, every NOVA-filled Steam order would understate margin by 2% of
   face value.

This ADR is the sequel to 0081 and does not repeat its reasoning about the reserve pattern, the
sentinel-vs-kind tradeoff, or `RESERVE_SUPPLIERS` — only what is new here: a second sentinel
mapping (Steam), a margin expression that now has to read two different truths depending on
whether a supplier stated its own charge, and two seeds that turn the reserve pattern's
consequences into a real catalogue and sourcing change — not yet run against production; see
"Validation" below.

Design: `docs/superpowers/specs/2026-09-17-nova-steam-and-free-fire-design.md`.
Runbook: [`docs/runbooks/nova.md`](../runbooks/nova.md).

## Decision drivers

- A supplier's own stated charge is data; a constant we maintain describing what we assume they
  charge is a guess that silently drifts. NOVA's Steam plan (`bronze|silver|gold`) can change
  without telling us.
- The reserve pattern from ADR-0081 (mapping is inert, `force_supplier` is what moves orders)
  has to hold for every new mapping this branch adds, Steam included — nothing here should be a
  second way to route to NOVA automatically.
- Free Fire's margin only exists if we actually switch the SKUs; a mapping alone changes nothing
  (ADR-0081 Decision 1). The owner chose to act on the measured price gap immediately rather than
  stage it.

## Considered options

1. **Do nothing about the discount** — leave `margin_usd_expr` as-is and accept that NOVA-filled
   Steam orders understate margin. Rejected: the whole point of a margin report is that it is
   right, and a reporting bug that only trips on the supplier a reserve currently doesn't route
   to is exactly the kind of thing nobody notices until the reserve is switched on.
2. **A `NOVA_STEAM_DISCOUNT = Decimal("0.98")` constant**, read wherever the margin is computed.
   Rejected — see Decision 2 below; a constant is a guess about a plan that can change without us
   knowing.
3. **Record what the supplier actually charged, once, and prefer it when present** (chosen for
   the margin problem).
4. **Stage Free Fire brand-by-brand or SKU-by-SKU**, watching each for a week before switching
   the next. Rejected by the owner — see Decision 3.
5. **Map and switch every Free Fire SKU in one seed run**, with an explicit rollback path
   (chosen).

## Decision outcome

Four decisions, each narrowing rather than widening what 0081 already established.

### 1. Steam is a second sentinel mapping, not a fourth `kind`

NOVA's Steam wallet top-up is a different endpoint from its games one
(`POST /api/v2/steam-topup/order`, takes `{steamLogin, currency, amount}`, answers `201` not
`200`), reached through `external_product_id = "steam-topup"` (`STEAM_SENTINEL` in
`fulfillment/suppliers/nova.py`), `kind = "game"`, no real variant.

This is exactly the tradeoff ADR-0081 Decision 3 already worked through for the validate
namespace, applied a second time: `ck_sku_supplier_mapping_kind` still allows only
`voucher|game|gift`, and the admin's mapping wizard still coerces whatever `kind` it loads to
`voucher`/`game` on save (`MappingEditPage.tsx`). A fourth `kind` would need a migration and would
be silently rewritten the first time an operator opened and re-saved the mapping page; a sentinel
in a column the wizard round-trips untouched survives that. `nova.py`'s `fulfill()` branches on
`category_id == STEAM_SENTINEL` before it ever reads `external_variant_id`, so the games and
Steam paths cannot cross — both directions are asserted by test
(`test_a_games_mapping_never_reaches_the_steam_call`,
`test_a_steam_mapping_sends_the_login_and_the_line_amount`).

**A gap this decision nearly left, found while writing the runbook and fixed here instead.** The
admin mapping wizard requires a non-empty "Номинал" (`external_variant_id`) for any `kind="game"`
mapping unless the supplier is amount-priced, and that check knew only about G-Engine's `unfixed`
services. NOVA was not on the list, so the Steam sentinel mapping could not be created from the
admin at all — the reserve would have shipped unreachable, with the runbook telling an operator to
type a placeholder into a field the adapter never reads.

The fix is deliberately narrow. `_is_amount_priced` (`integrations/service.py`) now also admits a
`nova` mapping whose `external_product_id` is the Steam sentinel, and nothing else: a NOVA **game**
mapping still requires its offer id and still refuses to save without one. Adding `nova` to the set
outright was the obvious move and the wrong one — it would let an operator save a game mapping with
no offer, and the first order on it would fail at our own guard instead of at the form, moving the
feedback from the moment of the mistake to the moment it costs a customer their order. Both halves
are asserted (`test_novas_steam_mapping_needs_no_variant`,
`test_a_nova_game_mapping_still_needs_its_offer`).

The sentinel itself moved to `integrations/models.py` beside `RESERVE_SUPPLIERS` for the same
reason: two unrelated callers now need the same fact — the adapter, to know which of NOVA's two
order endpoints a line belongs to, and the mapping validator, to know which single row may carry no
variant. One definition, or they drift and the admin starts refusing a mapping the adapter would
have used.

**And a third caller, which the first attempt at this fix forgot.** The admin wizard keeps its own
copy of the rule in `apps/admin/src/features/integrations/types.ts` — the backend decides what it
will accept, the wizard decides whether Save is even clickable. Fixing only the backend left the
Steam reserve exactly as unreachable as before, with a runbook confidently describing a step that
ended at a disabled button. The frontend gate now takes the product id as well as the supplier and
mirrors the same narrow rule, its docstring says the mirror is the point, and a wizard test asserts
both halves. The lesson generalises past this branch: a validation rule that exists on both sides of
the API has two homes, and a change to one is a change to both.

### 2. Margin reads what the supplier actually charged, not an assumed dollar-for-dollar cost

`orders.revenue.margin_usd_expr` gained a new leading branch: for a variable-amount SKU with a
recorded `OrderItem.cost_usdt`, margin is `qty × unit_price_usd × multiplier − qty × cost_usdt`
instead of the old `qty × unit_price_usd × (multiplier − 1)`. The old branch is still there,
unchanged, for every line with no recorded cost — which today is every historical Steam order (0
of 316 on production carried one before this branch).

**Why `OrderItem.cost_usdt` and not a new column**: it already means exactly this for fixed SKUs
("what this line cost us, frozen at checkout", [ADR-0053](./0053-freeze-the-cost-a-line-was-bought-at.md)),
and no variable line has ever written to it, so its meaning is not being overloaded on any existing
row.

**Who writes it, and when**: `fulfillment.service._record_supplier_charge`, called from both sites
that merge a fulfiller's `extra_metadata` onto the task — the inline `fulfill()` path and the
reconciliation poll. Written once (guarded by `item.cost_usdt is not None`, safe because both
callers hold the row for update) and never overwritten by a later poll, because NOVA states the
charge twice (`novaDebit.amountUsd` on create, `chargedUsd`/`charged_usd` on a fetched order) and a
restatement must not move a figure a margin report has already summed.

**A stated `"0"` or `NaN` is refused rather than written**, and this was not the first version of
the guard — a review pass caught that the naive version let either through. `cost_usdt` carries a
positive CHECK constraint (`ck_order_items_cost_usdt_positive`), so a `0` would raise an
`IntegrityError` _after_ the supplier was already paid and the goods already delivered, rolling
back a task that should have succeeded and reporting a delivered top-up as a failure for a human to
re-settle. `NaN` is quieter and worse: Postgres sorts it above every numeric, so it would pass the
CHECK and poison every margin sum over the window it landed in. Neither is a cost, so
`_record_supplier_charge` now requires the figure to be positive and finite before writing it;
anything else is logged (`fulfillment.supplier_charge_not_a_cost`) and dropped, and the order still
delivers normally. Five parametrised cases in
`apps/api/tests/integration/test_fulfillment_supplier_cost_recording.py` pin this.

**The margin tests run against real SQL, not a Python mirror of it.** `margin_usd_expr` returns a
SQLAlchemy `Case`; a hand-written Python re-implementation of the same arithmetic would assert
that the mirror agrees with itself, not that the expression that actually runs in production is
correct. No test in this repo executes a SQLAlchemy `Case` without a real database — SQLite cannot
stand in (JSONB columns, cross-table FKs) — so these tests live in
`apps/api/tests/integration/test_steam_supplier_cost_margin.py` rather than `tests/unit/`, which is
DB-free by convention here. That placement was flagged during implementation as a brief deviation
and confirmed correct on review rather than silently changed back.

**Multiplier precedence needed a test that could actually fail.** The first version of the "frozen
rate wins over the live SKU rate" test used a fixture where both numbers agreed, so it passed
whichever one the code read — caught by mutation testing, not by inspection. The fixture now pins a
frozen rate (1.10) against a disagreeing live SKU rate (1.20) so reading the wrong one fails.

### 3. Free Fire CIS is switched wholesale, not staged

The owner's call: map all nine existing SKUs and switch every one of them to NOVA in the same
seed run (`SWITCH_TO_NOVA = frozenset({"free-fire"})` in `scripts/seed/2026-09-17_nova_mappings.py`),
rather than switching one SKU, watching it for a week, and moving to the next. The six diamond
denominations pair through the existing number-and-unit matcher; the three memberships (Weekly
Lite, Weekly Membership, Monthly Membership) carry no denomination number, so they go through a
small **explicit** `SKU_OFFER_OVERRIDES` table read once by a human rather than fuzzy-matched by
name — a name is exactly the thing that must not be guessed when the guess routes money, and
`_offers_by_id`/`_override_claim` still run every override through the same claims-and-collisions
pass a denomination match does, so an override can't silently double-claim an offer NOVA happens to
list twice.

Mobile Legends and PUBG stay mapped-but-reserve, exactly as ADR-0081 left them; only `free-fire` is
in `SWITCH_TO_NOVA`, and that set is the only thing gating which brands this seed can move live
traffic for.

**The cost of being wrong is one admin action.** If NOVA's Free Fire price moves above G2B's after
this ships, the rollback is not a deploy: Admin → Sourcing → the SKU → mode "Авто" removes the
`force_supplier` rule and `_resolve_auto` falls back to the oldest remaining active mapping (the
G2B incumbent, per ADR-0081 Decision 4) — per SKU, or all nine, whichever the price move affects.
Nothing needs re-seeding; the G2B mappings were never touched or deactivated by this seed.

**The seed script itself changed shape mid-branch.** It started as something that printed tables
and committed in the same breath, which was fine while it only wrote inert mappings — but once it
started writing `force_supplier` rules too, that same breath started moving live orders before an
operator had read the output. It is now a **dry run by default**; `APPLY=1` is the second,
deliberate step. See the runbook for the exact invocation.

### 4. The ten NOVA-only SKUs need an explicit rule — a direct consequence of ADR-0081's reserve rule

`scripts/seed/2026-09-18_free_fire_nova_only.py` creates ten new SKUs (a new `free-fire-packs`
product for six Level Up Packages and the Newbie Bundle; three Evo Access durations joining the
existing `free-fire-membership`) whose _only_ supplier is NOVA — there is no G2B equivalent to fall
back to. ADR-0081's `RESERVE_SUPPLIERS` means auto sourcing skips NOVA whatever a mapping's age or
provenance, so without an explicit `force_supplier = nova` rule these ten would look sellable in
the storefront and land in the manual admin queue on every single order. The seed writes that rule
in the same transaction as the mapping, for exactly this reason — there is no "let auto sourcing
figure it out" option once a SKU's only mapping is a reserve supplier.

Priced at cost × 1.10 ceiled to the cent (the owner's decision, matching the 9–11% the brand's
existing SKUs already carry), and each SKU also gets `margin_percent = 10` so the hourly
supplier-price job keeps re-deriving `price_usd` at that margin as NOVA's cost moves, rather than
freezing the shelf price the day the seed ran — matching what every other Free Fire SKU already
carries (9–13%, per production).

`free-fire-packs` copies `required_fields` from `free-fire-diamonds` **verbatim** rather than
retyping it, because `brand_check_field` ([ADR-0079](./0079-region-brands-and-brand-level-player-check.md))
returns a player check only when every active product of a brand agrees on its check config — a
new product with a different or absent `check` block would silently disable the check for the
_whole_ Free Fire brand, not just itself. The regression test for this trap
(`apps/api/tests/integration/test_player_check_brand_agreement.py`) asserts both directions: a
second active product with matching `required_fields` keeps the check alive, and one with a flipped
field turns it off and logs the mismatch.

Same dry-run-by-default shape as the mapping seed, for the same reason: this seed also writes
`force_supplier` rules. `APPLY=1` commits; anything else prints the table and rolls back.

### Positive consequences

- Margin reporting now tells the truth about NOVA's Steam discount once an operator switches the
  SKU — the 2% gap is visible rather than silently absorbed, and the fix generalises: any future
  supplier whose charge differs from face value benefits from the same branch without further code
  changes, as long as it states its charge the way NOVA does.
- Free Fire CIS margin improves by the measured 0.8–3.6%, and ten previously-unsellable items
  (there was no other route to sell a Level Up Package or Evo Access at all) become real SKUs.
- The reserve pattern from ADR-0081 held under its first real stress test: two brand-new mapping
  shapes (a sentinel with no catalogue entry, ten SKUs with no incumbent) and neither broke the
  invariant that nothing routes to a reserve supplier without an explicit `force_supplier` rule.

### Negative consequences

- **No live Steam order has ever been placed through NOVA.** Everything about the Steam path —
  the `201` status, the `availablePlans`/`balanceUsd` 400 shape, `_finish`'s no-id guard, the debit
  fold — is verified by contract and unit tests against NOVA's documented and observed-elsewhere
  behaviour, not against a real Steam top-up run through this exact endpoint. The games path had
  exactly this gap when ADR-0081 shipped, and the first live order there (`docs/runbooks/nova.md`)
  corrected three things the documentation had wrong. The Steam path should get the same treatment
  before it is trusted with real volume, and the runbook records what that first order needs to
  capture.
- The mapping validator now has a second reason to allow an empty variant, and it is keyed on one
  supplier plus one literal id (Decision 1). That is a narrow exception on purpose, but it is still
  an exception: a third amount-priced shape should widen `_is_amount_priced` deliberately rather
  than by pattern-matching another sentinel into it.
- Free Fire's price advantage at NOVA is a snapshot from 2026-09-17. Nothing in this branch alerts
  if NOVA's price rises back above G2B's — an operator has to notice, the same as any other
  supplier-price comparison in this codebase. The rollback is cheap (Decision 3) but not automatic.
- `fulfillment/service.py` is 2844 lines, pre-existing and already far past the AGENTS.md §6
  400-line soft limit / 500-line split mark. This branch added one function
  (`_record_supplier_charge`) to it rather than to a new file, on the grounds that splitting an
  2800-line saga file mid-branch is its own project; the file is not smaller for this branch having
  touched it.

## Validation

- **Contract** (`apps/api/tests/contract/test_nova_client.py`): the Steam order's `201` (a real
  difference from the games endpoint's `200`), the two-decimal amount rule, the `availablePlans`
  400 shape kept intact in the refusal message, and an id-less create response reading as an empty
  dict rather than crashing.
- **Unit** (`apps/api/tests/unit/test_nova_fulfiller.py`): a games mapping never reaches the Steam
  call and vice versa; the Steam branch sends the login and the line's face-value amount; a missing
  `steam_login` is refused before any call; a Steam refusal is graded and redacted the same way a
  games refusal is; the Steam low-balance stall.
- **Integration** (`apps/api/tests/integration/test_steam_supplier_cost_margin.py`): the real SQL
  invariant `gross − margin == cost` on a variable line with and without a recorded cost, a fixed
  line untouched, a discount cancelling out of the invariant, the SKU-multiplier fallback, and the
  frozen-vs-live multiplier precedence (the case caught by mutation).
- **Integration** (`apps/api/tests/integration/test_fulfillment_supplier_cost_recording.py`): the
  fulfil path records a stated charge; no charge, nothing written; a fixed SKU is left alone even
  with a stated charge; a later poll never moves a cost the create already wrote; the poll path
  records a charge when the create never stated one (the only-recording-path case); a `0`/`NaN`/
  negative/non-finite charge is logged and dropped rather than written.
- **Integration** (`apps/api/tests/integration/test_player_check_brand_agreement.py`): the
  ADR-0079 trap — a second active product with matching `required_fields` keeps the brand's player
  check alive; one that disagrees turns it off and logs why.
- Both seeds were exercised before this ADR, short of an `APPLY=1` run against production: the
  mapping seed's matching/override/collision logic against a throwaway script run directly, the
  new-SKUs seed as a full dry run against dev with a faked NOVA response, rolled back after.
  **Neither has been run with `APPLY=1` against production as part of this branch** — that is an
  operator's deliberate next step, not something merging this branch does on its own. See each
  script's own docstring for the exact invocation and the runbook for how to read the printed
  tables before committing.
- No test places a real NOVA order of either kind, and the Steam path specifically has never been
  exercised end-to-end — see "Negative consequences" above and the runbook's "first live order"
  section, which is empty on purpose until someone runs one.

## References

- [ADR-0081](./0081-nova-reserve-supplier.md) — the reserve pattern, `RESERVE_SUPPLIERS`,
  `MAPPING_REQUIRED_SUPPLIERS`, and the sentinel-vs-kind reasoning this ADR extends rather than
  repeats.
- [ADR-0053](./0053-freeze-the-cost-a-line-was-bought-at.md) — why `OrderItem.cost_usdt` is the
  right column to extend rather than a new one.
- [ADR-0079](./0079-region-brands-and-brand-level-player-check.md) — the brand-wide player-check
  agreement that `free-fire-packs` has to satisfy.
- Design: `docs/superpowers/specs/2026-09-17-nova-steam-and-free-fire-design.md`.
- Runbook: [`docs/runbooks/nova.md`](../runbooks/nova.md) — the Steam and Free Fire sections this
  ADR assumes.
