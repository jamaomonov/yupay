# CS2 skins — plan 4: admin and ops

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps are
> RED → GREEN; every task ends with its suite green and a commit. Never push.

**Goal:** operators can see every skin trade (and which ones need a human), edit skin pricing
without SQL, and learn within a day when Waxpeer's view of a trade diverges from ours.

**Architecture:** two read/write admin endpoints on the existing `/admin/skins` router, two
admin SPA pages under a new «Скины» nav entry, and one daily scheduler job that re-reads the
last 14 days of our trades from Waxpeer and alerts on divergence. No new dependency.

**Tech stack:** FastAPI + SQLAlchemy async (api), APScheduler (scheduler), Vite + React 19 +
TanStack Query 5 + `@yupay/ui` (admin), vitest + testing-library, pytest integration.

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` §6.5, §9 item 4. Owner scope
(2026-09-29): trades screen, pricing screen, 14-day sweep + alert. Merchant API exposure is
**plan 5**, not here.

## Global constraints

- Admin routes: `require_admin`; writes take `Idempotency-Key` (`yupay.core.idempotency`).
- Admin lists: `limit` (default 50, clamped 1–500) + `offset`, response `{items, total}`.
- Admin copy lives in `packages/i18n/locales/{ru,en,uz}/admin.json` under a new `skins`
  namespace, all three locales in the same commit.
- No external HTTP call from an admin request handler (AGENTS.md §10).
- Never log a trade link or its token; seller names are public Steam names (spec §2.3).
- Money in minor units: Waxpeer units (1 unit = $0.001) shown as dollars in the UI.

## Rulings made while planning

- **The 14-day sweep reads `check-many-project-id`, not `my-history`** — the former's shape is
  proven on prod (spike §8.1) and keyed by our own `project_id`; `my-history`'s response shape
  was never captured and the key works only from the prod IP, so it cannot be tested here.
  Cost: a Waxpeer purchase with no row of ours (an orphan buy) is not detected — that needs a
  one-off prod probe of `my-history` and is recorded in the runbook as open.
- **No "recheck now" button** — an in-flight trade is re-read every 5–10 s already, and an
  accepted one hourly; a button would add a write endpoint for no faster answer.
- **"Needs attention"** = Waxpeer status 6 with penalties (a rollback), or our state is failed
  with reason `support`, or the task sits in `buy_pending`/`buy_unconfirmed` (money may have
  moved without a trade id).

## Review focus

1. A trade whose order item or task was deleted/missing — the list must still render.
2. The pricing form sending brackets that the server refuses (422) — the error is shown, the
   form keeps the operator's input.
3. A history sweep over >100 trades — batches of 100 (`check_project_ids` limit).
4. Waxpeer unreachable during the sweep — the job logs and returns, never alerts falsely.
5. An item override cleared (`null`) versus left unchanged (field absent).

---

### Task 1: API — list skin trades

**Files:** `modules/skins/admin.py` (route), `modules/skins/admin_trades.py` (query + DTO
builder, new), `modules/skins/schemas.py` (`AdminSkinTradeOut`, `AdminSkinTradesOut`),
`migrations/versions/0090_skin_trades_created_idx.py`, test
`tests/integration/test_skins_admin_trades.py`.

**Produces:** `GET /api/v1/admin/skins/trades?view=all|active|attention&q=&limit=&offset=` →
`{items: AdminSkinTradeOut[], total}` newest first. `AdminSkinTradeOut`: `id, order_id,
order_item_id, created_at, market_hash_name, phase, paid_units, bought_units, waxpeer_status,
state (SkinTradeState), reason_code, reason, penalties, seller_name, trade_id, send_until,
release_date, accepted_at, last_checked_at, task_status, task_sub_state, attention: bool`.
`q` matches order id prefix or name (ILIKE). `active` = state in buying/offer_sent/accepted
(not released). Index `ix_skin_trades_created_at` (created_at DESC).

Tests (RED first): lists newest first with total; `active` excludes released/failed;
`attention` includes a status-6-with-penalties row and a support row, excludes a plain
declined refund; `q` by order-id prefix; non-admin → 403.

### Task 2: API — find a skin item for an override

**Files:** `modules/skins/admin.py`, `schemas.py` (`AdminSkinItemOut`), test
`tests/integration/test_skins_admin_items.py`.

**Produces:** `GET /api/v1/admin/skins/items?q=&limit=20` → `{items: AdminSkinItemOut[]}` with
`slug, name, phase, category, image_url, min_auto_units, count_auto, sell_price_usd,
margin_override_pp, fixed_price_usd`. `q` over `search_text`, ordered by `count_auto desc`.
Tests: finds by partial name; returns overrides; limit clamp.

### Task 3: Scheduler — 14-day history sweep

**Files:** `modules/fulfillment/skin_sweeps.py` (`audit_recent_trades`), job
`apps/scheduler/src/yupay_scheduler/jobs/skins_history_audit.py` (daily, 04:30 Asia/Tashkent,
gated on `waxpeer_api_key` and `cs2_skins_enabled`), `main.py` registration, tests in
`tests/integration/test_skins_sweeps.py` (logic) and `apps/scheduler/tests/` (registration).

**Produces:** `audit_recent_trades(db, client, *, alert, days=14) -> int` (divergences found).
Divergence = Waxpeer's status differs from ours on a row we consider settled:
- ours accepted/released, Waxpeer 6 → «откат после доставки» (+ penalties);
- ours failed (customer refunded), Waxpeer 4 or 5 → «скин ушёл, а деньги вернули»;
- ours has a row, Waxpeer has no trade for the project id → «Waxpeer не знает сделку».
In-flight rows are skipped (the 5 s sweep owns them). One alert per divergence,
`kind="skin_history_divergence"`, order id and Waxpeer status in the text. Waxpeer
unavailable → log, return 0.

Tests: each divergence alerts once; agreeing rows are silent; 150 rows → two lookups;
client error → no alert.

### Task 4: Admin SPA — trades page

**Files:** `apps/admin/src/features/skins/{api.ts,SkinTradesPage.tsx,SkinTradesPage.test.tsx}`,
`app/router.tsx`, `app/Layout.tsx` (nav «Скины» in «Операции»), `lib/queryKeys.ts`,
`components/StatusChip.tsx` (`skinTrade` domain), `admin.json` ×3.

**Produces:** `/skins/trades` — tabs Все / В процессе / Требуют внимания (URL-bound), search
box, `DataTable` (date, order ref, item, price $, state chip, seller, Steam-trade/offer
deadline or protection date, reason), `Pagination`. Row click → `/orders/{order_id}`.
Tests: renders rows from the mocked API; switching tab sends `view=attention`; empty state.

### Task 5: Admin SPA — pricing page

**Files:** `features/skins/{SkinPricingPage.tsx,PricingRulesCard.tsx,PricePreviewCard.tsx,
ItemOverrideCard.tsx}` + tests, router/nav (`/skins/pricing`), `admin.json` ×3.

**Produces:** rules form (expenses %, retail + b2b brackets as editable rows, liquidity bands,
category/weapon pp maps, min margin, floor, UZS rounding, cap at Steam) saved with PUT and an
Idempotency-Key minted per save attempt; server 422 shown inline, input kept. Preview card
(cost, category, channel, count, item pp, fixed, steam) showing the breakdown. Item override
card: search (Task 2), pick, set/clear margin pp and fixed price (PATCH with `null` to clear).
Tests: save sends the edited document with an Idempotency-Key; 422 message shown; preview
renders the breakdown; clearing an override sends `null`.

### Task 6: Docs + checks

Runbook (`skins-purchase.md`: admin screens, the daily audit and its three alert texts, the
open orphan-buy item), module-map row, `docs/api` regenerated (`make gen-api`), admin README
if it lists pages. Suites: api integration for skins, scheduler tests, admin vitest + tsc,
`prettier --check .`.
