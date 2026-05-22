# 17. Task-oriented admin refactor

- **Status**: Accepted
- **Date**: 2026-05-22
- **Deciders**: @jamaomonov
- **Tags**: frontend | backend | admin | ux

## Context and problem statement

The admin SPA (see [ADR-0010](./0010-admin-auth-via-telegram-roles.md), [ADR-0016](./0016-miniapp-vite-stack.md))
grew page-by-page along domain entity boundaries: one model = one list + one form. That shape
optimises for the developer who is wiring CRUD against new tables, not for the operator who
sits in front of it eight hours a day.

Operators do not think in tables. They think in **tasks**:

- "разобраться с жалобой клиента"
- "закрыть очередь ручных выдач за смену"
- "понять почему висят платежи"
- "не дать кодам закончиться"

A task-oriented operator currently has to copy IDs across five screens (Users → Orders →
Payments → Wallet → Audit) to answer the simplest support question. Dashboard alerts show
counts but are not clickable. Filter state lives in `useState` and is lost on reload, so
operators can't share a working view via URL. There is no global search — the entry point
for every scenario is "guess which list the entity is in, then filter by ID".

We need to evolve the admin into a **task-shaped tool** without throwing away the parts that
already work (the FSM-aware Order detail page, the typed manual-fulfilment modal, the
double-entry wallet adjust page, the unified audit feed).

## Decision drivers

- **Operator time on golden paths.** Most-frequent scenarios (customer-360, manual-queue, payment
  triage) should be one navigation away, not five.
- **Backwards compatibility.** Existing admin endpoints stay; new aggregate views compose them.
- **Service-layer reuse.** Quick actions invoke existing service methods so audit, idempotency
  and validation are inherited for free.
- **Incremental, low-risk migration.** No big-bang rewrite. CRUD pages that aren't painful stay
  as-is.
- **Future-proof for roles.** Granular roles are out of scope for now (binary `admin` only,
  per [ADR-0010](./0010-admin-auth-via-telegram-roles.md)), but UI groups quick actions
  semantically (support / finance) so role gates can be added later without re-layout.

## Considered options

1. **Big-bang rewrite** — design every screen around scenarios from scratch. High disruption,
   long lead time, parallel maintenance of old and new.
2. **Stay CRUD, layer dashboards on top** — keep existing pages, add a richer dashboard. Cheap
   but does not fix the cross-entity navigation pain.
3. **Incremental task-shaped refactor with cross-cutting foundation first.** Add a small layer
   of foundation (global search, URL-state filters, clickable alerts), then deliver
   high-value scenarios one at a time (Customer 360 → Fulfillment Inbox → Payments Triage).

## Decision outcome

**Chosen option: 3.** Incremental refactor.

### Sprint 0 — foundation (this ADR)

- **Global search** — `GET /admin/search?q=...&limit=N` returns grouped hits (orders, users,
  payments, skus) with deep-link paths. UI: `cmd+k` palette.
- **URL-state for filters** — `useSearchParamsState<T>` hook over RR7 `useSearchParams`,
  rolled out across Orders / Payments / Fulfillment / Users.
- **Clickable Dashboard alerts** — each alert card becomes an anchor to the corresponding
  filtered list (depends on URL-state).
- **No role split** — `require_admin` stays binary. Quick actions are grouped semantically
  for future role gating but functionally unrestricted today.

### Sprint 1+ — scenarios

- **Customer 360** (next) — `GET /admin/customers/{user_id}/overview`, page `/customers/:id`
  with tabs Orders / Payments / Wallet / Activity + quick actions (refund last, adjust wallet,
  open Telegram). Composes existing services; no new mutation endpoints.
- Later: Fulfillment Inbox, Payments Triage, Admin Activity view, Saved segments.

### Positive consequences

- Operators stop copying IDs for the most common workflow.
- Dashboard alerts become actionable, not just informational.
- Shareable filter URLs unblock async coordination ("вот ссылка на висящие платежи").
- Aggregate endpoints (`/admin/customers/:id/overview`) become a reusable composition pattern
  for future scenarios.

### Negative consequences

- Two navigation entry points for users will coexist for a while (`/users/:id` and the new
  `/customers/:id`). We accept the duplication during migration; the old route stays as a
  thin redirect target.
- Aggregate endpoints touch multiple modules — they must be guarded against N+1 with a
  dedicated SQL-count integration test per endpoint.

## Validation

- `cmd+k` opens the search palette and resolves any of: order UUID prefix, user email,
  Telegram `@username` or numeric `tg_user_id`, payment UUID prefix, SKU code.
- Filters survive page reload, are restorable via URL, and a shared link reproduces the same
  view for another admin.
- Each Dashboard alert card navigates to the corresponding list with the right filter applied.
- `make lint typecheck test` is green; no existing test changes behaviour expectations.
- New aggregate endpoint(s) have an integration test asserting bounded SQL query count.

## Alternatives considered (detail)

### Option 1 — big-bang rewrite

Pros: clean final state. Cons: every existing operator workflow breaks at once; long
parallel-stack period; the team is small.

### Option 2 — dashboards over CRUD

Pros: minimal disruption. Cons: dashboards alone do not solve the cross-entity navigation
problem (the single biggest pain). Operators still copy IDs.

## References

- [ADR-0010](./0010-admin-auth-via-telegram-roles.md) — admin auth & binary role model.
- [ADR-0016](./0016-miniapp-vite-stack.md) — admin Vite stack (no SSR).
- `docs/architecture/sequence-diagrams/admin-global-search.mmd` — sequence for `/admin/search`.
- Plan file: `~/.claude/plans/pure-purring-dream.md` (analysis + roadmap).
