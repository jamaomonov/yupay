# 0025. Analytics dashboard: a `/analytics` admin page backed by two range-parameterised, Redis-cached read-only endpoints in `stats`

- **Status**: Accepted
- **Date**: 2026-06-04
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | observability

## Context and problem statement

The admin already has an operational `GET /admin/stats/dashboard` that reports
**last-24h KPIs** — order counts by status, today's revenue, inventory low-stock,
recent webhook failures. It answers "is the system healthy right now?" but says
nothing about **trends** or **business performance over a window**: how revenue
and margin move week-over-week, where the orders come from (brand/SKU mix), how
the purchase funnel converts, how many customers are new vs returning, and
whether payments / fulfilment / inventory are degrading over days rather than
hours.

We want a second, complementary surface: a **business + operations analytics
view over a chosen window** (7 / 30 / 90 days) with proper trend charts, sitting
alongside — not replacing — the 24h operational Dashboard.

A wrinkle is **margin**. We do not (yet) store the supplier cost of each order
item at order time. The only cost we can read today is the SKU's _current_
`sku.cost_usdt`, and some SKUs have no cost recorded at all. So any margin we show
is necessarily **approximate** and must be labelled as such.

## Decision drivers

- **Different cadence and audience** from the 24h Dashboard — trends over days,
  read by someone asking "how is the business doing?", not "is it on fire now?".
- **Cheap to render, cheap to serve.** Trend aggregations scan many rows; the
  endpoints must be cached so opening the page is not a heavy DB hit every time.
- **Honesty about margin.** With no order-item cost snapshot, margin is an
  estimate; the API and UI must say so rather than imply precision.
- **Charts cost real engineering.** Axes, tooltips, legends, responsive resize,
  and React 19 compatibility are not free if hand-rolled.
- **No data-model change for a read-only reporting feature** if avoidable.

## Considered options

1. **Hand-rolled SVG charts** over the existing 24h Dashboard data.
2. **Extend the existing 24h `GET /admin/stats/dashboard`** with trend fields and
   render the new view inside the current Dashboard page.
3. **Denormalise order-item cost** (snapshot cost at order time) so margin is
   exact, then build the analytics view on top.
4. **A dedicated `/analytics` admin page (two tabs, 7/30/90d)** backed by two
   range-parameterised, Redis-cached, read-only endpoints in `stats`, charted
   with a charting library; margin computed approximately from current
   `sku.cost_usdt`.

## Decision outcome

**Chosen option: Option 4.**

A new admin-only **`/analytics` page** with two tabs — **Бизнес** (business) and
**Операционка** (ops) — each with a **7d / 30d / 90d** range selector, backed by
two new read-only endpoints in the existing `stats` module:

- **`GET /admin/stats/analytics/business?range={7d|30d|90d}`** → `BusinessAnalyticsOut`
  (revenue & approximate margin trend, purchase funnel, brand/SKU mix, new vs
  returning customers).
- **`GET /admin/stats/analytics/ops?range={7d|30d|90d}`** → `OpsAnalyticsOut`
  (payments health, fulfilment health, inventory health over the window).

Both are admin-only (the module's existing admin dependency), parse `range` and
dispatch only — the aggregation lives in service functions.

**Charts: recharts 3.x.** We adopt **recharts 3.x** for the charts. recharts 3
natively supports React 19 (the admin SPA's React version), giving us axes,
tooltips, legends and responsive containers out of the box.

**Caching.** Each endpoint caches its computed payload in Redis under
`stats:analytics:{business|ops}:{7d|30d|90d}` with **TTL 300s**. The cache is
**best-effort**: on a Redis read/write error the endpoint falls back to live
computation and still serves the response, so analytics never goes down because
Redis is unavailable. Invalidation is **time-only** — no explicit busting; trend
data tolerates a 5-minute staleness window.

**Margin is approximate.** The margin numerator and denominator are computed
**only over order-item rows where `sku.cost_usdt IS NOT NULL`**; NULL-cost rows
are excluded from the margin maths. The payload surfaces this honestly:

- a `margin_approx` flag marks the figure as an estimate;
- `margin_unknown_units` counts the quantity of units whose SKU has no recorded
  cost (i.e. excluded from the margin calc);
- per-brand / per-SKU `margin_usd` is `None` for any group that has **no**
  known-cost rows, rather than silently reporting 0.

**No FX P&L KPI.** The design brief floated an FX P&L headline of
`Σ(total_charged − total_usd)`. We **dropped it**: `total_charged` is stored in
each order's _native_ currency (e.g. UZS), while `total_usd` is in USD, so the
difference subtracts unlike units and yields a meaningless figure for any non-USD
order. A correct realised-FX metric needs a USD-equivalent snapshot of
`total_charged` at settlement, which we do not store — deferred with the
denormalisation work in option 3.

**Code organisation.** The analytics aggregation SQL is split out of
`stats/service.py` into a dedicated **`stats/analytics.py`** module, keeping the
operational dashboard logic and the heavier trend aggregations separate.

### Positive consequences

- A trend/business view that complements, rather than overloads, the 24h
  Dashboard, with first-class charts via recharts 3.x.
- Opening the page is cheap and resilient: 5-minute Redis cache with a
  live-compute fallback when Redis is down.
- Margin is shown honestly — flagged as approximate, with the unknown-cost volume
  exposed — instead of pretending to a precision we cannot back.
- No migration: the feature is purely read-only aggregation over existing tables.

### Negative consequences

- A new frontend dependency, **`recharts`** (3.x), in the admin SPA.
- `stats` now **reads many domains** (orders, order_items, payments,
  payment_webhooks, fulfillment_tasks, inventory_codes, catalog, users,
  integrations) read-only for aggregation, widening its read surface.
- Analytics aggregations are split into `stats/analytics.py`, a second file the
  module must keep coherent with `service.py`.
- **Margin stays best-effort** until order-item cost is denormalised; an SKU
  cost change retroactively shifts historical approximate margin, and NULL-cost
  SKUs are invisible to the margin figure (only counted in `margin_unknown_units`).

## Validation

- Both endpoints return their typed models (`BusinessAnalyticsOut` /
  `OpsAnalyticsOut`) for each of `7d` / `30d` / `90d` and reject other `range`
  values.
- The cached response matches a live-computed response within the TTL window, and
  the endpoint still returns a valid payload when Redis is unavailable
  (live-compute fallback).
- Margin fields behave as specified: `margin_approx` is set, `margin_unknown_units`
  reflects NULL-cost quantity, and a group with only NULL-cost rows reports
  `margin_usd = None`.
- Integration tests for the `stats` analytics endpoints (coverage ≥ 80%).

## Alternatives considered (detail)

### Option 1 — hand-rolled SVG charts

Reject. Rebuilding axes, tick formatting, tooltips, legends, and responsive
resize by hand is substantial, error-prone work for no advantage over a
maintained library that already supports React 19.

### Option 2 — extend the existing 24h Dashboard

Reject. The 24h Dashboard answers a **different question** (live operational
health) for a **different cadence** and audience. Bolting multi-day trend fields
and a range selector onto it would muddle both surfaces and force the operational
view to carry heavier aggregations it does not need.

### Option 3 — denormalise order-item cost for exact margin

**Deferred, not rejected.** Snapshotting supplier cost onto each order item at
order time would make margin exact and immune to later cost changes. But it
requires a migration and a change to the order-creation flow (capturing cost at
the moment of sale). That is a larger, order-path change; the analytics view does
not justify it on its own. Until then, margin is computed from current
`sku.cost_usdt` and flagged as approximate. When the cost snapshot lands, the
analytics aggregation switches its source and drops the `margin_approx` flag.

## Amendment — 2026-09-16: arbitrary windows, a calendar, and a channel split

Three things the original decision did not carry, added without a second
endpoint or a second computation.

**An explicit window beside the presets.** `business` now also accepts
`since`/`until` (`until` exclusive). A preset range and "that Tuesday" and
"1–15 September" are the same aggregation over a different pair of bounds, so
they stay one endpoint; the calendar paints a month by asking for that month.
`range` is `null` in the response whenever the window was explicit, so the
client never has to guess which form it asked for.

**A calendar tab.** A month grid where each cell carries the day's revenue and
its margin, tinted by margin relative to the best day on screen. Revenue alone
cannot say which days were good — a day can take $400 and keep $12 — so the
tint is keyed on the number being compared. Clicking a day opens the ordinary
business tab scoped to it.

**A channel split (`channel={all|retail|b2b}`).** Retail and wholesale have
genuinely different economics: a reseller buys at a thinner markup, so a blended
margin flatters one half and libels the other. The parameter scopes the _whole_
tab — funnel, mix, customers, the comparison window — because "which brands does
the wholesale side actually buy" is the question being asked, and answering it
from a blended payload would mean re-deriving it client-side from rows the
payload no longer carries. `Order.merchant_id` is the entire distinction.

**The one deliberate exception**: the «Розница и B2B» comparison block is _not_
scoped. It is the thing the scoping is compared against; narrowing it would
leave a single row reading 100%.

User-registration figures are also left unscoped, with a comment at the query
saying so — a user account belongs to no channel, and a reseller's end customers
never register with us.

**Cache keys grew to match.** `stats:analytics:business:{window}:{channel}`. A
key that does not carry the whole question serves a month's grid from whatever
range happened to be asked for first, which is a wrong answer that looks right.

## References

- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — catalog three-level model (Brand/Product/SKU)
- [ADR-0011](./0011-order-fsm-and-snapshots.md) — order FSM and pricing snapshots
- [ADR-0010](./0010-admin-auth-via-telegram-roles.md) — admin auth / roles
- `docs/superpowers/specs/2026-06-04-analytics-dashboard-design.md` — feature design spec
- `docs/architecture/cache-keys.md` — `stats:analytics:ops:{range}`, `stats:analytics:business:{window}:{channel}`
- `docs/architecture/module-map.md` — `stats` read surface
- `apps/api/src/yupay/modules/stats/analytics/` — `business.py`, `ops.py`, `_common.py`
