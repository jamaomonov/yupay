# 0081. NOVA as a reserve supplier and a player-check fallback

- **Status**: Accepted
- **Date**: 2026-09-17
- **Deciders**: owner, Claude
- **Tags**: backend | data

## Context and problem statement

Two independent pressures, one supplier answers both.

**Fulfilment has no reserve for game top-ups.** G2B is the only route for
every game brand we sell. When G2B is out of stock on a denomination, short
on balance, or down, the order lands in the manual admin queue and a human
finishes it. G-Engine is a second source (ADR-0052), but only for Steam and a
handful of titles — it does not cover MLBB, PUBG, Free Fire or the rest.

**The player check has no fallback at all.** `POST /catalog/brands/{slug}/check-player`
and `POST /merchant/v1/validate/player` both end at G2B (or Waxpeer for
Steam). When the primary rate-limits us, errors, or is unreachable, every
check answers `error` — the storefront shows "не удалось проверить" and the
reseller cabinet shows nothing. `validate/player` is the same brand-scoped
check as the storefront's (ADR-0079), calling the same G2B bucket, so a
busy reseller and busy retail traffic now compete for one rate limit.

NOVA (`nova-gifts.com`) sells both: 306 top-up categories covering
essentially our whole game catalogue, and a `validate-id` endpoint for five
games — two of which are the region-split pair (Magic Chess: Go Go
Global / RU, ADR-0079) our own catalogue already splits the same way.

Two facts from probing their live API on 2026-09-17 shape every decision
below: **our balance is `$0.0000` and no order has ever been placed on this
key**, and **their order object is untyped in their own OpenAPI** (`order: {}`).
Both make caution — a reserve rather than a primary, a fallback that can
only ever soften an `error` — the only defensible starting posture.

## Decision drivers

- A supplier outage should cost margin or a wait, never the sale and never a
  wrongly-blocked customer.
- The player check is advisory (ADR-0031): `invalid` is the one verdict that
  blocks Pay, and adding a second supplier to the check must not add a
  second way to reach that verdict on evidence nobody has validated yet.
- NOVA's own docs contradict themselves on what a reused `Idempotency-Key`
  does (one description says the original order is returned, the other that
  the request is rejected), and with a zero balance we could not find out
  which was true before this shipped. Whatever we built had to be safe under
  either answer. **Settled since, by the first live order on 2026-09-17: the
  request is rejected** with a `409`, so a create is never safely retried
  under the same key — which is what the adapter already assumed by grading a
  409 `UNKNOWN`. The endpoint description is simply wrong; the parameter
  description is right.
- `sourcing._resolve_auto` was written when every top-up SKU had exactly one
  active supplier mapping. NOVA is the first thing that legitimately gives a
  SKU two, and the existing code's behaviour under that condition had never
  been decided, let alone tested.

## Considered options

1. **Do nothing.** G2B stays the only route and the only check. Rejected: it
   is the status quo this ADR exists to change, and NOVA's catalogue overlap
   is too close to our own to leave unused.
2. **NOVA as a reserve supplier and an advisory check fallback** (chosen).
3. For the validate target: a `kind="validate"` row on `sku_supplier_mapping`,
   as the original sketch proposed, instead of a code table. See Decision 3
   below for why this was narrowed away from.
4. For a region mismatch on the fallback: read it as `invalid`, as the
   original sketch proposed, instead of `error`. See Decision 2 below.

## Decision outcome

**Chosen option:** Option 2, with four decisions that each narrow the design
rather than widen it.

### 1. NOVA is a reserve, not a second automatic route

The mapping is active, but the sourcing rule stays on the incumbent
supplier; switching is only an explicit admin action
(`force_supplier = nova` in `sourcing.set_rule`, refused without an active
mapping — `nova` is in `MAPPING_REQUIRED_SUPPLIERS`). No supplier→supplier
failover chain is built here, in either direction. This mirrors G-Engine's
role for Steam (ADR-0052): a second source earns trust order by order, not
by being wired into the primary path the day it is registered, and an
automatic chain would mean a NOVA outage or price change could move volume
without anyone deciding to.

### 2. The player-check fallback never answers `invalid`

It is consulted **only** when the primary answered `error` — never instead
of `valid`/`invalid`, never to second-guess them — and from there it can
turn that `error` into `valid`. It can never turn anything into `invalid`.
Three reasons, in order of weight:

1. It runs only when there is no primary verdict, so its `invalid` would be
   the **sole** basis for blocking a paying customer, on a supplier we have
   never validated against our brand namespaces.
2. NOVA's single `mobile_legends` validate category has only ever been
   observed answering for a Russian account; whether it also validates
   global accounts, and what its `region` field says for one, is unknown
   (open question, design doc §10). That is exactly why global Mobile
   Legends has no fallback entry in `NOVA_VALIDATE` at all — a brand we
   cannot tell apart from another gets no fallback rather than a guess.
3. It matches how this module already treats an answer it cannot fully
   read: `player_check._map_response` returns `error`, not `invalid`, for a
   G2B verdict outside the two it recognises, precisely to avoid becoming a
   fake rejecter. A region mismatch on a matched brand gets the same
   treatment (`_verdict` in `player_check_nova.py`), which is the one place
   this ADR overrides the original sketch: the sketch read a mismatched
   region as `invalid`, this ships it as `error`.

The cost is a customer who mistypes an id during a primary outage sees "не
удалось проверить" instead of "неверный ID" — which is exactly what they
saw before this shipped, so there is no regression. The gain — a confirmed
nickname while the primary is down, for five brands — is kept in full.

### 3. The validate target is a code table, not a `sku_supplier_mapping` row

`NOVA_VALIDATE` in `player_check_nova.py` is a plain module-level
`dict[str, NovaValidateTarget]`, keyed by brand slug, holding at most six
entries. The original sketch put NOVA's validate category in
`sku_supplier_mapping` with a new `kind`. Three concrete costs made that the
more expensive option, each verified against the code as it stands today:

- `ck_sku_supplier_mapping_kind` (the CHECK constraint on
  `sku_supplier_mapping.kind`, `integrations/models.py`) allows only
  `'voucher','game','gift'` — a fourth kind needs a migration.
- `sourcing.service._resolve_auto` selects an active mapping **without
  filtering on `kind`**: `select(SkuSupplierMapping.supplier_slug).where(sku_id == …, is_active.is_(True))`.
  A `validate`-kind row on a top-up SKU would become a candidate fulfilment
  route the moment it existed, not just a check target.
- The admin mapping wizard coerces any loaded mapping's kind to
  `voucher`/`game` on save (`MappingEditPage.tsx:108`:
  `kind: existing.data.kind === "voucher" ? "voucher" : "game"`), so
  opening and re-saving a `validate` row would silently rewrite it.

Validation is brand-scoped; mappings are SKU-scoped. A reviewed table of at
most six brand slugs is the smaller, safer carrier for that mismatch, and it
costs a deploy to extend rather than an admin edit — which is correct here,
because adding a brand also means someone has to think about what its
`region` word means (Decision 2).

### 4. Auto sourcing never picks a reserve, and otherwise picks the oldest mapping

`sourcing.service._resolve_auto` used to pick a top-up SKU's active
`sku_supplier_mapping` with `.limit(1)` and **no `ORDER BY`**. That was
stable by accident: every top-up SKU had exactly one active mapping, so the
missing sort never had anything to disagree about. NOVA, as a reserve, is
the first legitimate way for a SKU to carry two active mappings at once
(its incumbent plus NOVA), and without a sort the answer becomes whichever
row Postgres happens to return first — which can change after a `VACUUM`,
silently moving orders to a different supplier with nothing to announce it.

Fixed in two parts, and the second was missed on the first pass.

Ordering the query `created_at ASC, supplier_slug ASC` makes the choice
deterministic: the incumbent mapping is the older row, so every SKU's
routing today is unchanged.

But ordering alone makes "reserve" an accident rather than a rule. It keeps
the incumbent's route only while an incumbent **exists** — and for a top-up
SKU that never got a G2B mapping (the likeliest state for a brand, per
`docs/runbooks/merchant-b2b.md`), or one whose only mapping an operator
deactivated mid-switch, NOVA's mapping _is_ the oldest. That SKU would have
started buying from a supplier nobody chose. With the key unset it is worse
than quiet: the adapter refuses before calling, graded `RETURNED`, so orders
that used to wait in the manual queue would fail and refund instead.

So `RESERVE_SUPPLIERS` (`integrations/models.py`) names the suppliers auto
sourcing skips entirely, whatever a mapping's age or provenance — a seed
run, an admin edit, a deactivated incumbent. Reaching NOVA is an explicit
`force_supplier` decision (Decision 1) and nothing else.
`test_auto_never_routes_to_a_reserve_supplier` is where that is true rather
than asserted.

Both are behaviour changes to an existing function, made because this branch
is what first makes the previously-impossible case (two active mappings on
one SKU) real; they are recorded here so they stay findable.

### Positive consequences

- A failing G2B route has somewhere to go for essentially the whole game
  catalogue, without an operator building a new adapter first.
- The player check survives a primary outage for five brands instead of
  going fully silent, and a merchant sharing G2B's rate limit with retail
  traffic (ADR-0079) gets the same relief.
- The `_resolve_auto` determinism gap (Decision 4) is fixed **before** it
  could bite silently — NOVA is the trigger, but the fix protects every
  future reserve supplier too.

### Negative consequences

- A fourth supplier's quirks to keep in mind, and its wallet to keep
  funded — **the account balance is $0.0000 today**, so the adapter is
  wired but cannot fulfil anything until the first live order (see
  `docs/runbooks/nova.md`).
- Their order object being untyped means the status table in `nova.py` is
  an allow-list built from prose, not from a schema; an unrecognised status
  stays `in_progress` and logs `nova.unknown_order_status` rather than
  guessing. It will need at least one real order to confirm or correct.
- **`player_check.py` is now 550 lines**, past the 500-line "split before"
  mark in AGENTS.md §6 (it was already 506 before this branch, so the split
  is not new debt this branch created, only debt it grew). The module mixes
  three things that used to be one: G2B/Waxpeer verdict resolution, the
  dispatch into the NOVA fallback, and the breaker/cache plumbing shared by
  both. A natural split is the NOVA dispatch (`_nova_brand`/`_nova_steam`)
  and its two lazy imports moving out to `player_check_nova.py`, which
  already owns the rest of the fallback and already imports from
  `player_check.py` today — that import direction would simply invert. This
  is scoped as its own piece of work rather than folded into this branch,
  and is recorded here rather than left as a bare `TODO` per AGENTS.md §13.
- **The admin health probe covers NOVA, and it was written because this
  document nearly recorded that it did not.** Writing these consequences
  surfaced that `GET /api/v1/admin/integrations/{supplier_slug}/health` checks
  the slug against `_KNOWN_SUPPLIERS` in `integrations/routes.py` and then
  calls the adapter's own `health()` — and that NOVA was in neither. The
  admin's frontend list already carried `nova`, so its card would have read
  "unknown supplier" whether or not the key was set. That is the wrong thing
  to be wrong about for a **reserve**: nothing routes to NOVA on an ordinary
  day, so a dead key or an empty balance is discovered at the moment somebody
  needs it, and the probe is what moves that discovery earlier.
  `NovaFulfiller.health()` now answers with the key's validity and the wallet
  balance from `GET /api/v2/balance`, the same shape G-Engine and Waxpeer use.

## Validation

- **Contract** (`apps/api/tests/contract/test_nova_client.py`): auth header,
  the `ok:false`-on-200 refusal, cursor paging, the 403
  `subscription_inactive` shape, `validate-id` success/negative/422,
  `check-login`, and `create_topup_order` sending `Idempotency-Key`.
- **Unit** (`apps/api/tests/unit/test_nova_fulfiller.py`): every row of the
  §4.2 money table in the design doc; an unrecognised status staying
  `in_progress`; field mapping; the missing-mapping refusal.
- **Unit** (`apps/api/tests/unit/test_player_check_nova.py`): primary
  `valid`/`invalid` never call NOVA; primary `error` + NOVA `valid` →
  `valid` with the name; a NOVA negative → `error`; a region mismatch →
  `error`; a brand absent from `NOVA_VALIDATE` → `error` with no call; an
  open breaker → no call; the Steam `can_refill` branch both ways; the
  cache namespace.
- **Integration** (`apps/api/tests/integration/test_inventory_sourcing_routes.py`):
  two active mappings on one SKU resolve deterministically to the older
  one, verified by mutation (dropping `created_at` from the `ORDER BY`
  fails the new test and still passes the old one); `force_supplier=nova`
  is refused without a mapping and accepted with one.
- **Integration** (`apps/api/tests/integration/test_nova_reconcile.py`): a
  finished order is reconciled, a still-`processing` one is left alone, one
  bad task never stops the sweep, and another supplier's tasks are ignored.
- **Money-outcome matrix** (`apps/api/tests/unit/test_supplier_money_outcome.py`):
  NOVA's grading added alongside G2B/G-Engine/Waxpeer's.
- No test places a real order, and none should: a test that spends money at a
  supplier is a test nobody can run twice. That validation happened once, by
  hand, and is written down in `docs/runbooks/nova.md` — one 60 UC PUBG
  Mobile top-up on 2026-09-17, completed in 8 seconds, `created -> processing
-> completed`, order id `ord-1372576` under the key `id`, charged on create.
  It confirmed the status allow-list unchanged and corrected three things the
  documentation had us believe: a reused idempotency key is refused rather
  than replayed, their live error envelope is not the documented one (the
  useful sentence is in `message`), and a bad `offer_id` answers `502` with
  the balance untouched. Each correction is pinned by a contract or unit test
  so it cannot quietly regress.

## References

- [ADR-0031](./0031-storefront-player-check.md) — the advisory player check
  this fallback extends; its `invalid`-blocks-Pay rule is why Decision 2 is
  the whole shape of the fallback.
- [ADR-0052](./0052-g-engine-as-a-second-source.md) — the precedent for a
  second source treated as a reserve, not a replacement.
- [ADR-0079](./0079-region-brands-and-brand-level-player-check.md) — the
  brand-scoped check this fallback plugs into, and the region-split brands
  NOVA's validate namespace happens to mirror.
- Design: `docs/superpowers/specs/2026-09-17-nova-supplier-design.md`
- Runbook: `docs/runbooks/nova.md`
