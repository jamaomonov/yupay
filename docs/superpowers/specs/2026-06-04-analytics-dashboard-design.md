# Design: Admin analytics dashboard (`/analytics`)

**Date:** 2026-06-04
**Status:** Approved (brainstorming) — pending implementation plan
**Surface:** Admin SPA (`apps/admin`) + API (`apps/api`, `stats` module)
**Branch:** `main` (per user instruction)

---

## 1. Problem

The admin has an operational `GET /admin/stats/dashboard` (24h KPIs: order counts, status
breakdown, 7-day sparkline, inventory) rendered by `apps/admin/src/routes/Dashboard.tsx`. There
is no **trend / business** view: revenue over time, margin, average order value, product mix,
conversion funnel, customer growth, payment-provider and supplier health over a chosen window.

Build a dedicated **`/analytics`** page with a period selector (7 / 30 / 90 days) and two tabs —
**Бизнес** (money & growth) and **Операционка** (payments, fulfilment, inventory health). The
existing 24h Dashboard stays untouched.

## 2. Goals / Non-goals

**Goals**

- New `/analytics` admin route, two tabs, range selector (7d/30d/90d, default 30d).
- Two range-parameterised backend endpoints in the existing `stats` module, one per tab.
- Charts (line/bar/donut) + KPI cards + top-N tables, grounded in real aggregates.
- Approximate gross margin from current `sku.cost_usdt` (flagged `approx`).
- Short-TTL Redis cache on the aggregation endpoints.

**Non-goals (deferred)**

- Denormalising cost/fee/fulfilment-cost (precise per-order margin) — margin stays **approximate**.
- CSV export, custom date ranges, wallet/loyalty tab (group H), Prometheus business metrics.
- Touching the existing 24h Dashboard.

## 3. Decisions (locked during brainstorming)

- **Audience:** both — one page, two tabs (Бизнес + Операционка).
- **Margin:** approximate now — `Σ(order_item.qty · sku.cost_usdt)` vs revenue; surfaced with an
  `approx: true` flag and a UI "оценочно" note. Rows where `sku.cost_usdt IS NULL` are excluded
  from the margin numerator/denominator and counted as `margin_unknown_units`.
- **Page:** new `/analytics`; the 24h Dashboard is unchanged.
- **Charts:** `recharts` (new dependency in `apps/admin`, justified by an ADR).
- **Canonical money:** USD via `orders.total_usd`; a secondary breakdown by `orders.currency`
  uses `total_charged`. FX P&L = `Σ(total_charged − total_usd)` over the window.

## 4. Backend

Extend the `stats` module (`apps/api/src/yupay/modules/stats/{routes,service,schemas}.py`). The
admin router prefix is `/admin/stats` (admin-only via the module's existing dependency).

### 4.1 Endpoints

Both accept `?range=7d|30d|90d` (default `30d`), validated as an enum. Range → a `since`
timestamp (`now() - N days`); all aggregates filter `created_at >= since`.

- **`GET /admin/stats/analytics/business`** → `BusinessAnalyticsOut`:
  - `summary`: `gmv_usd`, `orders`, `paid_orders`, `delivered_orders`, `aov_usd`,
    `fx_pnl_usd`, `gross_margin_usd` (approx), `margin_pct` (approx), `margin_approx: true`,
    `margin_unknown_units`.
  - `revenue_series`: daily `[{date, revenue_usd, orders}]` via `date_trunc('day', paid_at)`
    over paid/delivered orders (zero-filled for empty days in the service layer).
  - `funnel`: counts per status `{created, paid, fulfilling, delivered, cancelled, expired,
refunded}` + `payment_conversion_pct` = paid ÷ created.
  - `top_brands` / `top_skus`: top-N (N=10) `[{slug/name, revenue_usd, units, margin_usd?}]`,
    joined order_items → sku → product → brand.
  - `customers`: `new_users_series` (daily), `guest_orders` vs `registered_orders`,
    `repeat_rate_pct`, `top_locales` `[{locale, users}]`.

- **`GET /admin/stats/analytics/ops`** → `OpsAnalyticsOut`:
  - `payments`: `[{provider, count, volume_usd, success_rate_pct}]`, `stuck_pending` count
    (`status='pending' AND created_at < now()-30m`), `webhook_unhealthy`
    (`signature_ok=false OR processed_at IS NULL`).
  - `fulfillment`: `[{supplier, total, success_rate_pct, avg_seconds, manual_count,
avg_attempts}]`, `stuck_tasks` (`status IN ('pending','in_progress') AND
next_attempt_at < now()`). `avg_seconds` = `AVG(succeeded_at − created_at)` over succeeded.
  - `inventory`: `low_stock` `[{sku_code, available}]` (available < 10), `expiring_soon`
    (`available AND expires_at < now()+7d`).
  - `supplier_cost`: recent `supplier_price_history` changes `[{sku_code, supplier_slug,
cost_usdt, previous_cost_usdt, captured_at}]` within the window (top 20 by `captured_at`).

### 4.2 Implementation

- Service functions in `stats/service.py` run SQL aggregations (`date_trunc`, group-by,
  `COUNT FILTER (WHERE …)` for success rates). No ORM row loading — aggregate `select()`s only.
- Pydantic v2 output models in `stats/schemas.py`; routers parse `range` + dispatch only.
- **Caching:** wrap each endpoint result in Redis with TTL 300s, key
  `stats:analytics:{tab}:{range}` (`tab` ∈ business|ops). Use the project's existing async Redis
  accessor (the plan verifies the helper; if none is wired in `stats` today, mirror the pattern
  used elsewhere — e.g. `core`/`payments` Redis usage — or compute live as a documented
  fallback). Document the keys in `docs/architecture/cache-keys.md`.
- **Indexes:** the group-bys lean on `orders.created_at/paid_at/status`,
  `payments.provider/status/created_at`, `fulfillment_tasks.supplier/status/created_at`. The plan
  confirms these exist; any missing index is added in the same migration. No new tables.

### 4.3 Performance

At 1–5k orders/day a 90-day window is ≲450k orders; indexed aggregates + 300s cache keep this
well within budget. Each list endpoint's query count is asserted by an integration test
(AGENTS.md §10). Heavy joins (order_items→sku→brand) are bounded to top-N.

## 5. Frontend (admin SPA)

**Route/nav:** add `/analytics` to `apps/admin/src/app/router.tsx` (under the authed Layout) and a
sidebar link in `apps/admin/src/app/Layout.tsx`.

**Files** (`apps/admin/src/features/analytics/`):

- `AnalyticsPage.tsx` — thin container: `PageHeader`, range selector (segmented 7/30/90), tabs
  (Бизнес / Операционка). TanStack Query keyed `(tab, range)`; only the active tab fetches.
- `BusinessTab.tsx` — KPI row (GMV, orders, AOV, margin≈, FX P&L) → revenue `LineTrend` → funnel
  `FunnelBars` → product mix (`DonutShare` + top-brand/SKU `DataTable`) → customers (new-users
  `LineTrend`, guest/registered `DonutShare`, locales table).
- `OpsTab.tsx` — payments (`BarBreakdown` by provider + success-rate, stuck/webhook badges) →
  fulfilment (`DataTable` by supplier + avg time) → inventory low-stock `DataTable` → supplier
  cost-change table.
- `charts/{LineTrend,BarBreakdown,DonutShare}.tsx` — thin recharts wrappers reading theme CSS
  variables; `KpiCard.tsx`, `FunnelBars.tsx`.
- `types.ts` — DTOs mirroring both endpoints; query-key factories added to
  `apps/admin/src/lib/queryKeys.ts`.

Conventions: CSS variables, Russian strings (admin has no i18n), lucide icons, existing
`PageHeader`/`DataTable`/`Button`/`Spinner`/`States`. Each tab file kept ≤300 LOC (split a chart
section into a child if it grows). New dep `recharts` in `apps/admin/package.json`.

## 6. Testing (AGENTS.md §8)

- **Backend** (`stats` coverage ≥80%) — `apps/api/tests/integration/test_stats_analytics.py`
  (testcontainers Postgres): seed orders (varied statuses/dates), order_items+skus (with and
  without `cost_usdt`), payments (providers, success/fail), fulfilment_tasks (suppliers,
  success/fail, timings). Assert: range filtering, `summary` numbers, `revenue_series` daily
  buckets, funnel + conversion, top-brands ordering, payment/fulfilment success rates, margin
  approx excludes NULL-cost rows and sets `margin_approx`. One test asserts the cache path
  (second call served from Redis / no recompute) if caching is wired. A query-count assertion on
  each endpoint guards N+1.
- **Frontend** — admin has no unit-test suite; verify `tsc` (0), `lint` (0 on new files),
  `prettier` clean, and a manual run on the live stack (tabs, range switch, charts render, KPIs
  reconcile with DB).

## 7. Documentation (AGENTS.md §5)

- ADR `docs/decisions/0025-analytics-dashboard.md` — recharts dependency, the two analytics
  endpoints, and the approximate-margin decision + its limitations.
- `docs/architecture/cache-keys.md` — `stats:analytics:{tab}:{range}` (TTL 300s).
- `docs/architecture/module-map.md` — `stats` reads orders/payments/fulfilment/catalog/users/
  integrations for read-only aggregation.
- `make gen-api` — regenerate `docs/api/openapi.json` + `packages/api-client`.

## 8. Definition of Done

- [ ] `GET /admin/stats/analytics/business` + `/ops` implemented, range-validated, admin-only.
- [ ] Aggregates correct; margin approximate with `approx` flag and NULL-cost exclusion.
- [ ] Redis cache (TTL 300s) with documented keys (or documented live-compute fallback).
- [ ] `/analytics` page: two tabs, range selector, charts, KPI cards, top tables; recharts added.
- [ ] Backend integration tests green; coverage ≥80% on new code; query-count asserted.
- [ ] OpenAPI + TS client regenerated; no drift.
- [ ] ADR 0025 + cache-keys + module-map updated.
- [ ] `make lint typecheck test` green; admin `tsc`/`lint`/`prettier` clean.
- [ ] Manual run verified (numbers reconcile with DB).
