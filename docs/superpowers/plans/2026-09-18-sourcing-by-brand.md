# Sourcing by Brand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect per-supplier costs, let exactly the routed supplier own `Sku.cost_usdt`, stop the automatic path from lowering a retail price, and give the admin a brand-scoped screen that compares suppliers and switches many SKUs at once.

**Architecture:** `refresh_sku_cost_for_mapping` becomes supplier-dispatched and always records history; only the routed supplier writes the SKU's cost. `set_sku_cost_usdt` gains a ratchet flag. Two new read/write endpoints back one new admin screen.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, httpx, pytest + respx; React 19 + TanStack Query in the admin SPA.

**Spec:** `docs/superpowers/specs/2026-09-18-sourcing-by-brand-design.md`

## Global Constraints

- **`Sku.cost_usdt` is our cost basis, not a fact about a supplier.** Retail price derives from it, order lines freeze it at checkout, the margin report subtracts it. Exactly one supplier may write it: the one `sourcing.resolve_for_sku` says the SKU routes to. Every other active mapping records history and touches nothing else.
- **The automatic path may raise a price and may not lower it.** A cost drop is a saving we keep (the owner's decision); a cost rise still raises the price, which is what protects the margin. An operator editing a cost by hand may still lower it.
- **A reserve supplier is never offered as an automatic route** (`RESERVE_SUPPLIERS`, ADR-0081). A screen that lets someone pick one as "auto" would undo that.
- **Never lower a price as a side effect of a refactor.** Any change here that moves `price_usd` on a SKU nobody edited is a defect, and a test must be able to catch it.
- Steam mappings (`NOVA_STEAM_SENTINEL`) have no catalogue price and are skipped by the cost sync entirely.
- `ruff` line-length 100, `mypy --strict` — **run it from the repo root over `apps`, which includes tests**, and run `uv run ruff format --check apps` too, not just `ruff format` on the files you touched. Google docstrings.
- Admin: TypeScript strict, no `any`. A validation rule that exists on both sides of the API has two homes — change one, change both (ADR-0082's lesson).
- No pushing, no deploying, no prod database writes. Branch: `feat/sourcing-by-brand`.

---

## File Structure

| File                                                                        | Responsibility                                                                      |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `apps/api/src/yupay/modules/integrations/service.py`                        | supplier-dispatched cost fetch; history for every mapping; the routed-supplier rule |
| `apps/api/src/yupay/modules/catalog/admin_service.py`                       | `set_sku_cost_usdt(..., allow_price_drop)`                                          |
| `apps/api/src/yupay/modules/integrations/price_refresh.py`                  | passes `allow_price_drop=False`; the alert says the direction                       |
| `apps/api/src/yupay/modules/sourcing/routes.py`, `service.py`, `schemas.py` | the brand overview and the bulk write                                               |
| `apps/admin/src/features/sourcing/BrandSourcingPage.tsx`                    | the screen                                                                          |
| `apps/admin/src/features/sourcing/SourcingPage.tsx`                         | the rules table it keeps, enriched and filterable                                   |

---

## Task 1: Per-supplier costs, and only the routed supplier owns ours

**Files:**

- Modify: `apps/api/src/yupay/modules/integrations/service.py` (`refresh_sku_cost_for_mapping`, ~line 492)
- Test: `apps/api/tests/integration/` (the price-refresh suite — find it with `rg -l refresh_sku_cost_for_mapping apps/api/tests`)

**Interfaces:**

- Produces: `refresh_sku_cost_for_mapping` handling `g2b` and `nova`, always writing `supplier_price_history`, and writing `Sku.cost_usdt` only for the routed supplier. `CostRefreshOutcome` gains a field saying whether the SKU's cost was written or only history was.

- [ ] **Step 1: Write the failing tests**

Four cases, all against a SKU with **two** active mappings (`g2b` and `nova`) — the shape 22 production SKUs now have:

1. Refreshing the **routed** supplier's mapping writes `Sku.cost_usdt` **and** a history row.
2. Refreshing the **other** supplier's mapping writes a history row and leaves `Sku.cost_usdt` exactly as it was. Assert the old value, not just "not the new one".
3. Both histories are queryable afterwards and carry the right `supplier_slug` — this is the comparison the screen reads.
4. A NOVA **Steam** mapping (`external_product_id == NOVA_STEAM_SENTINEL`) is skipped with a reason and writes nothing at all.

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Dispatch by supplier**

Replace the `if mapping.supplier_slug != "g2b": return ...` guard with a dispatch. G2B keeps its existing body verbatim. NOVA's: skip the Steam sentinel, then `GET /topups/offers` for `external_product_id` and find the offer whose `offer_id` equals `external_variant_id`, taking `price_usd`. Cache the per-category response for the duration of one refresh run so a 19-SKU brand makes one call, not nineteen — the cache lives in the caller (Task 2), so this function takes an optional pre-fetched offers map.

- [ ] **Step 4: The routed-supplier rule**

Before writing the cost, resolve the route:

```python
    decision = await sourcing_api.resolve_for_sku(db, mapping.sku_id)
    routed = decision.primary == f"supplier:{mapping.supplier_slug}"
```

History is written either way. `set_sku_cost_usdt` is called only when `routed` is true, and the outcome says which happened so the caller can report it. Import `sourcing` lazily, as `integrations` already does elsewhere, to keep the dependency direction unchanged.

Explain in the docstring why: the cost is our basis for price, for a frozen order line and for margin, so two suppliers writing it would flip a SKU's retail price hourly depending on which refreshed last.

- [ ] **Step 5: Tests green, lint, typecheck, commit.**

---

## Task 2: A price that only ratchets up

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/admin_service.py` (`set_sku_cost_usdt`, ~line 414), `apps/api/src/yupay/modules/integrations/service.py` (its caller), `apps/api/src/yupay/modules/integrations/price_refresh.py` (the alert text, and the per-category cache from Task 1)
- Test: the catalog admin-service suite and the price-refresh suite

- [ ] **Step 1: Write the failing tests**

- A cost **drop** with `allow_price_drop=False` leaves `price_usd` byte-identical and still updates `cost_usdt`.
- The same drop with `allow_price_drop=True` lowers the price, as today.
- A cost **rise** raises the price under both flags — the margin protection must survive the change.
- A SKU with no `margin_percent` is untouched either way.
- The hourly path passes `False` and the admin path passes `True`: assert at the call sites, because a default that silently flips is exactly the bug this is preventing.

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: The flag**

`set_sku_cost_usdt(db, *, sku_id, new_cost, allow_price_drop: bool = True)`. Default `True` keeps every existing caller behaving as it does today; the hourly job is the one that passes `False`. Inside, the re-derive gains one condition: assign only when `allow_price_drop or candidate > sku.price_usd`.

The docstring says why a drop is not passed on — it is the owner's decision that a saving from switching suppliers is kept rather than handed to the customer — and that a rise still raises, because that half is what stops a supplier's price increase quietly eating the margin.

- [ ] **Step 4: One fetch per category**

In `price_refresh.refresh_all_mappings`, group the mappings by `(supplier_slug, external_product_id)` and fetch each NOVA category once, passing the offers map down. Nineteen Free Fire SKUs share one category; nineteen calls where one would do is how a supplier starts rate-limiting us.

- [ ] **Step 5: The alert says the direction**

`_format_alert` gains a line: which way the cost moved, and on a drop that the price was deliberately left alone. An operator reading "cost moved 3.6 %" with no direction cannot tell a saving from a squeeze.

- [ ] **Step 6: Tests green, lint, typecheck, commit.**

---

## Task 3: The brand overview endpoint

**Files:**

- Modify: `apps/api/src/yupay/modules/sourcing/routes.py`, `service.py`, `schemas.py`
- Test: `apps/api/tests/integration/` beside the existing sourcing tests

**Interfaces:**

- Produces: `GET /api/v1/admin/sourcing/brands/{brand_slug}` → for each active SKU of the brand: `sku_id`, `sku_code`, `denomination`, `product_slug`, `price_usd`, `cost_usdt`, the live route (`primary`, and whether a rule produced it), and a list of `{supplier_slug, has_active_mapping, latest_cost_usdt, captured_at}`.

- [ ] **Step 1: Write the failing test**

A brand with two products, several SKUs, mixed mappings and one explicit rule. Assert: one row per **active** SKU; the route matches `resolve_for_sku` for each; a supplier with no mapping appears with `has_active_mapping=false` and no cost; the latest history row wins when several exist.

**And assert the query count.** A brand has up to 35 SKUs and the screen is the thing an operator opens first — this endpoint resolves a route, reads mappings and reads price history for every row, which is three N+1s waiting to happen. Pin it the way the repo's other list endpoints do (`rg -l "query count\|assert_queries" apps/api/tests` for the existing helper).

- [ ] **Step 2: Run it, watch it fail.**

- [ ] **Step 3: Implement**

One query for the SKUs with their product, one for every active mapping of those SKUs, one for the latest history row per `(sku_id, supplier_slug)` — a `DISTINCT ON` or a window function, not a loop — and the routes resolved from the rules already loaded rather than by calling `resolve_for_sku` per SKU. If reusing `resolve_for_sku` per SKU is the only way to keep the answer honest, say so in the docstring and keep the count bounded by batching its inputs.

- [ ] **Step 4: Tests green, lint, typecheck, commit.**

---

## Task 4: The bulk switch endpoint

**Files:** `apps/api/src/yupay/modules/sourcing/routes.py`, `service.py`, `schemas.py`; tests beside Task 3's.

**Interfaces:**

- Produces: `PUT /api/v1/admin/sourcing/rules:bulk` taking `{sku_ids: [...], mode, supplier_slug}` and returning per-SKU results: `{sku_id, ok, error}`.

- [ ] **Step 1: Write the failing tests**

- Every listed SKU gets the rule, and the response says so per SKU.
- **A partial failure does not fail the batch**: one SKU forced onto a supplier with no active mapping is reported as failed **by name** while the rest are written. That is the behaviour that makes a bulk action usable — an all-or-nothing batch on a 35-SKU brand tells an operator nothing about which row was wrong.
- `mode="auto"` deletes the rules, as the single-SKU path does.
- A reserve supplier is accepted here only as `force_supplier`, never as an automatic route — the existing `set_rule` guard already does it; assert it survives the bulk path.
- The list is capped (100) so one request cannot walk the whole catalogue.

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Implement** by looping `set_rule` per SKU inside one session, catching `ValidationError` per item. Each success and each failure is its own line in the response.

- [ ] **Step 4: Tests green, lint, typecheck, `make gen-api` for the OpenAPI drift check, commit.**

---

## Task 5: The brand screen

**Files:**

- Create: `apps/admin/src/features/sourcing/BrandSourcingPage.tsx`, its test
- Modify: the admin router, `apps/admin/src/features/sourcing/types.ts`, and `SourcingPage.tsx` to link to it

- [ ] **Step 1: The test first** (`@yupay/admin` uses Vitest + Testing Library; `MappingEditPage.test.tsx` is the house shape)

- The table renders one row per SKU with its route and each supplier's cost, cheapest marked.
- A supplier with no active mapping is not offerable for that row, and the reason is visible rather than only a disabled control.
- Ticking rows and switching calls the bulk endpoint **once** with those ids.
- A partial failure renders which SKUs failed and why, and leaves the successful ones shown as switched.

- [ ] **Step 2: Build the screen** per the spec's §6 table. Brand picker at the top, reusing the existing brand picker if one exists (`rg -l "BrandPicker" apps/admin/src`), otherwise a plain select over `/catalog/brands`.

- [ ] **Step 3: Enrich the rules table** on `SourcingPage`: brand, product and denomination beside the code; a text filter; filters by supplier and mode. Keep the single-SKU editor — a one-off edit should not require choosing a brand first.

- [ ] **Step 4: `pnpm --filter @yupay/admin exec vitest run` and `tsc --noEmit`, commit.**

---

## Task 6: Documentation

**Files:** `docs/decisions/0083-*.md`, `docs/runbooks/nova.md`, `apps/api/src/yupay/modules/sourcing/README.md`, `apps/api/src/yupay/modules/integrations/README.md`.

- [ ] **Step 1: ADR-0083** recording the three decisions a maintainer would second-guess: only the routed supplier writes `Sku.cost_usdt` (and what breaks otherwise — 22 SKUs would flip price hourly); the automatic path ratchets prices up only, with the owner's reasoning; and per-supplier history for everyone, which is what makes comparison possible at all.

- [ ] **Step 2: The runbooks.** `nova.md`'s Free Fire section gains what the operator now sees: their cost syncs from NOVA, the price stays, the margin widens to ~13 %. The sourcing README gains the brand screen and the bulk endpoint.

- [ ] **Step 3: `npx prettier --check .`, commit.**

---

## Final gate

```bash
make lint typecheck test
npx prettier --check .
```

One gate at a time — two concurrent runs exhaust this machine's memory and both get killed.

Then `superpowers:finishing-a-development-branch`.
