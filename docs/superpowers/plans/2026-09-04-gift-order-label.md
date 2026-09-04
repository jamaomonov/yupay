# Steam Gifts — show the game name instead of «Любая сумма»

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (Steam Gifts is LIVE on prod).

**Goal:** Every place that labels a gift order shows the purchased game — «Steam Игры · Dead Cells» — instead of the service SKU's placeholder «Любая сумма».

**Architecture:** `steam-gift` is one service SKU standing in for ~4200 games, so its `denomination` is the literal placeholder «Любая сумма». The real name is already snapshotted server-side on the order line: `order_items.fulfillment_data.app_name` (+ `package_name` for the edition), written by `gifts/checkout.py::price_gift_line`. One server-side function, `build_item_display`, feeds 8 of the 10 render sites, and `fulfillment_data` is already in its scope — so overriding the displayed denomination there fixes the Telegram push, both admin order screens, both admin manual-fulfilment screens, the miniapp order card, the miniapp history and the web order cards at once, with no client deploy and no extra queries. Two sites bypass it and need their own touch.

**Tech Stack:** FastAPI + SQLAlchemy 2 (backend), Next.js 15 (web).

**Spec:** none — operator request (2026-09-04), from screenshots of the Telegram "Заказ выдан" push and the admin orders table both reading «Steam Игры · Любая сумма».

## Global Constraints

- **The label is `app_name`, plus ` · {package_name}` only when the edition name differs from the game name.** G-Engine usually names the base package exactly like the app (e.g. app "Grand Theft Auto V Enhanced" / package of the same name), so appending unconditionally would print the name twice.
- **Gate the override tightly.** `build_item_display` runs for EVERY order in the system. Apply the gift branch only when BOTH hold: the SKU is the gift SKU (`sku.sku_code == STEAM_GIFT_SKU_CODE`, imported from the gifts module — `orders/service.py` already imports from `yupay.modules.gifts`, so no new cycle) AND `fulfillment_data["app_name"]` is a non-empty string. Anything else keeps today's behaviour byte-for-byte.
- **Never widen what is exposed.** Only `app_name` / `package_name` are read. `fulfillment_data` also holds `invite_url` (the recipient's Steam profile) and `supplier_price_usd` (our wholesale) — neither may leak into a label. Note `supplier_price_usd` is already redacted from customer-facing order schemas; do not undo that.
- **Old orders must not break.** A gift order placed before the snapshot carried `app_name` simply falls through to today's placeholder — no crash, no empty label.
- mypy --strict, ruff, Google docstrings (backend); TS strict, no `any`, no uncommented `as` (web).
- Conventional Commits; do NOT push, do NOT deploy. Never stage the pre-existing dirty files (`Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`).

---

### Task N1: Backend — the display choke point and the admin ref label

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/service.py` (`build_item_display`, ~:112-140)
- Modify: `apps/api/src/yupay/modules/admin/service.py` (`get_refs`, ~:573-639)
- Test: `apps/api/tests/unit/` (a new or existing test module for `build_item_display`), `apps/api/tests/integration/test_admin_refs_routes.py`

**What `build_item_display` does today:** returns `OrderItemDisplay{brand_name, product_name, sku_code, denomination, region, image_url, variable_amount, product_kind}`; line ~127 sets `denomination = sku.denomination`, with an existing override for unit SKUs just below. `item.fulfillment_data` is a non-deferred JSONB column on the `OrderItem` already in scope — no load, no join, no schema change.

**Add** a gift branch alongside the unit-SKU override: when the gate above holds, `denomination` becomes the game label. Everything else about the returned display is unchanged.

**`get_refs` (`GET /admin/refs`)** is hand-rolled SQL that bypasses `build_item_display` and composes `label=f"{name} · {denom}"` itself (~:628-636). It already drives 9 admin pages (payments, customer, fulfilment, manual queue, audit, reviews, wallet…). `OrderItem` is already the driving table, so add `OrderItem.fulfillment_data` to the `select()` list — no new join — and apply the same gift branch. Keep the label format otherwise identical; `apps/api/tests/integration/test_admin_refs_routes.py:135` pins it.

**Steps:** tests first — a gift line with `app_name` renders the game name; with a differing `package_name` renders `"{app_name} · {package_name}"`; with a matching `package_name` renders just the game name; a gift line with NO `app_name` (an old order) still renders the placeholder; a NON-gift line (a Telegram Stars unit SKU and an ordinary voucher SKU) is byte-for-byte unchanged; the admin ref label carries the game name for a gift and is unchanged for everything else. Run to fail → implement → pass → `uv run pytest apps/api/tests -k "display or refs or orders" -q` plus the gifts suite, ruff, `uv run mypy apps` (repo-root invocation). Note running from the repo root picks up the local `.env`, which makes a few unrelated `test_uzum_config`/`test_payme_*`/flag-default tests fail — a known local artifact, ignore those. Commit `feat(api/orders): label a gift line with the game, not the placeholder denomination`.

---

### Task N2: Web — the order-detail line where the amount shadows the name

**Files:**

- Modify: `apps/web/src/components/order/OrderItems.tsx` (`itemHeadline`, ~:24-30)
- Test: the colocated test for that component (create one if absent, following the app's RTL conventions)

**Why this one is separate:** the `steam-gift` SKU is `variable_amount=true`, and `itemHeadline` prefers the formatted USD amount over the denomination for variable-amount lines — so a gift order's detail page currently reads «Steam Игры · $10.14» and will keep doing so even after N1, because that branch shadows `denomination` entirely.

**Change:** when the line is a gift (its `fulfillment_data.app_name` is a non-empty string), the game label wins over the amount; the `region` suffix behaviour and every non-gift line stay exactly as they are. Compose the label from `app_name`/`package_name` with the same rule as N1 (append the edition only when it differs).

**Steps:** tests first — a gift line renders the game name and not the dollar amount; a gift line whose edition differs also shows the edition; an ordinary variable-amount line (Steam wallet top-up) still shows its dollar amount; a fixed-price line is unchanged. Run to fail → implement → pass → `pnpm --filter @yupay/web test -- --run`, `tsc --noEmit`, lint. NEVER run `next build` on the host. Commit `fix(web): show the game on a gift order line instead of the charged amount`.
