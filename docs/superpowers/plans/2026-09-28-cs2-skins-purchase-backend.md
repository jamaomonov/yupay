# CS2 Skins — Purchase Backend (plan 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A signed-in customer pays for one specific Waxpeer listing of a skin; the listing is
bought for their trade link right after payment; the order follows the Steam offer to
«принят» (delivered) or, if it falls through, refunds itself to the customer's YuPay balance.

**Architecture:** The generic order pipeline carries the skin line, exactly like `steam-gift`
(ADR-0066): a variable-price SKU `cs2-skin` mapped to supplier `waxpeer` with mapping kind
`skin`; `orders.service.create_order` re-prices the line through `skins.checkout`; payment
starts the fulfilment task; `WaxpeerFulfiller` branches on the mapping kind into a new
`waxpeer_skins` module that buys with `buy-one-p2p` and tracks with `check-many-project-id`.
A `skin_trades` row mirrors each Waxpeer trade for the order page and for ops. A fast
next-attempt sweep follows live trades; an hourly sweep follows accepted trades through
Steam's 7-day protection. A failed skin task whose money is `RETURNED` refunds the order to
the customer's wallet with one ledger posting.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, APScheduler (apps/scheduler), httpx,
pytest + testcontainers + respx.

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` (§2, §3, §5, §6, §8.1).
ADR: `docs/decisions/0093-cs2-skins-via-waxpeer.md`.

## Global Constraints

- Owner decisions (2026-09-28): buy **at payment** (no ready gate); the customer may buy **any**
  listed offer; a failed purchase refunds **automatically to the YuPay balance**
  (card refunds stay a support action); «Мгновенная доставка» copy stands.
- Skins checkout requires a signed-in user (a wallet refund needs a wallet). Guests get 401.
- Buy only `auto` listings. Price guard: `buy-one-p2p` gets `price = expected_units`;
  a refusal is never retried at a higher price than the order paid for.
- Idempotency: `project_id = idempotency_key_for(task)`. A lost buy response is resolved by
  `check-many-project-id`, **never** by buying again.
- Acceptance rule (spike §8.1): status 4 **with `release_date`** = accepted → delivered;
  status 4 with `release_date = null` = offer sent; 6 before acceptance = failed/`RETURNED`;
  5 = released. `penalties` on a 6 after acceptance = rollback → alert, `SPENT`.
- The Waxpeer key works only from the prod IP: every Waxpeer call lives in api/worker/scheduler
  on prod; tests use respx, never the network.
- Trade link token is a secret-ish credential: never logged, never in an alert; order responses
  show the link only to its owner.
- Money in `Decimal`; Waxpeer units are integers (1000 = $1).
- **Nothing that changes minute to minute may be cached by Cloudflare, a browser or the web's
  fetch cache** (owner, 2026-09-28): order and trade progress, live offers, the trade-link check,
  balances. The API answers `Cache-Control: no-store` unless a route opts into its own policy.
- AGENTS §10: the trade-link check is an advisory external call in a request handler — it
  needs a line in AGENTS §10 and in ADR-0093, and its own rate-limit bucket, timeout and cache.

## Review Focus

1. A lost `buy-one-p2p` response followed by a retry must not buy twice (lookup first).
2. The chosen listing sold between payment and purchase → a same-name auto listing ≤ the paid
   units is bought instead; none → failed `RETURNED` → wallet refund, order `refunded`.
3. A refund can happen once per order, whatever mix of sweep, webhook replay or admin action.
4. A trade link whose Steam account is not the signed-in user's linked Steam account is refused
   at checkout (when a link exists).
5. Status 4 → accepted must be detected within ~10 s of Waxpeer reporting `release_date`.
6. A cached response (Cloudflare, browser, Next fetch cache) must never show an old order or
   trade state.

---

### Task 0: No caching of live data

**Files:** Create `apps/api/src/yupay/core/cache_headers.py` (middleware); modify
`apps/api/src/yupay/bootstrap.py` (install it); `docs/architecture/cache-keys.md` (HTTP caching
section); `infra/caddy/Caddyfile.prod` comment only if Caddy sets nothing.

- Middleware: every API response without a `Cache-Control` header gets
  `Cache-Control: no-store` (and `Vary: Authorization` stays as FastAPI sets it). A route that
  wants caching sets its own header explicitly — none does today.
- Web: the order pages and every client fetch of orders/listings use `cache: "no-store"`;
  server fetches of orders are `dynamic = "force-dynamic"`. Check `apps/web/src/lib/client.ts`
  and the order route segments; the skins catalogue keeps its 60 s ISR (prices every 5 min).
- Tests: `GET /api/v1/orders/{id}`, `/skins/{slug}/listings`, `/health` carry `no-store`; a
  route that sets its own header keeps it.

### Task 1: Schema and seed

**Files:** Create `apps/api/migrations/versions/0089_skins_purchase.py`,
`scripts/seed/2026-09-29_cs2_skin_sku.py`; modify `skins/models.py`,
`integrations/schemas.py` (`MappingKind` + `'skin'`), `tests/integration/conftest.py`
(`_EMPTY_IN_ORDER` += `skin_trades`, `skin_trade_links`).

- `skin_trades`: `id`, `order_item_id` (unique FK), `task_id` (FK), `waxpeer_id` (bigint, null
  until bought), `project_id` (unique), `listing_id` (bigint), `market_hash_name`, `phase`,
  `paid_units`, `bought_units` (null), `status` (smallint, Waxpeer's), `trade_id` (text),
  `send_until` (timestamptz), `release_date` (timestamptz), `is_released` (bool), `reason`,
  `penalties` (jsonb), `seller` (jsonb: name, avatar, level, joined), `accepted_at`,
  `last_checked_at`, `created_at`, `updated_at`. Index `(status, is_released)` for the hourly
  sweep.
- `skin_trade_links`: `user_id` (PK FK), `url`, `steam_id` (bigint), `updated_at` — the saved
  trade link.
- Widen `ck_sku_supplier_mapping_kind` with `'skin'`.
- Seed (dry-run default, `--apply`): brand `cs2-skins`, product `cs2-skin` (`kind="top_up"`,
  `required_fields=["slug","listing_id","tradelink"]`), variable SKU `cs2-skin`,
  `SkuSupplierMapping(sku, 'waxpeer', kind='skin')`.
- Tests: migration up/down; model round-trip; seed dry-run prints the plan and writes nothing.

### Task 2: Trade link — parse, check, save

**Files:** Create `skins/tradelink.py`, `skins/tradelink_routes.py`; modify
`waxpeer_client.py` (`check_tradelink`), `auth/steam.py` (`trade_hold_days`), `skins/api.py`,
router mount, `AGENTS.md` §9/§10, ADR-0093, `docs/architecture/cache-keys.md`.

- `parse_tradelink(url) -> TradeLink(partner:int, token:str, steam_id:int)`; accepts only
  `https://steamcommunity.com/tradeoffer/new/?partner=<digits>&token=<[\w-]{8}>`;
  `steam_id = partner + 76561197960265728`.
- `POST /skins/tradelink/check` (keyless advisory — AGENTS §9 list gains it with the reason:
  it writes nothing): parse → Waxpeer `check-tradelink` (info must be null) → Steam
  `IEconService/GetTradeHoldDurations` (hold must be 0) → `{ok, reason}` with reasons
  `invalid | private | trade_ban | hold | unavailable`. Timeout 4 s, Redis cache 10 min per
  `sha1(url)`, own `ip_guard` bucket `skins-tradelink`. `unavailable` never blocks checkout.
- `PUT /skins/tradelink` (Idempotency-Key): saves `skin_trade_links` for the user;
  `GET /skins/tradelink` returns it (owner only).
- Tests (respx): each reason; cache hit makes no upstream call; token never appears in logs
  (caplog); PUT idempotent on the key; 401 for guests.

### Task 3: Checkout pricing

**Files:** Create `skins/checkout.py`; modify `orders/service.py` (next to the gifts branch),
`orders/schemas.py` (`_CUSTOMER_HIDDEN_FULFILLMENT_KEYS` += `expected_units`,
`listing_units`), `orders/service.build_item_display`.

- `is_skin_sku(sku)`, `price_skin_line(db, *, user_id, line_amount_usd, data) -> dict`:
  - requires `user_id` (else `UnauthorizedError`);
  - `parse_tradelink`; if the user has a `SteamLink`, its `steam_id` must equal the link's
    (else `ValidationError(reason="tradelink_other_account")`);
  - loads the `SkinItem` by slug (active), gets current listings via `listings_for` (cached,
    budgeted — no new upstream path); finds `listing_id`; prices it with `pricing.quote`;
  - listing absent → `ValidationError(reason="listing_gone", extra={next_offer})` with the
    cheapest current offer (id, price);
  - server price vs client `amount_usd`: ±2 % tolerance, server price billed (gifts rule);
  - snapshot into `fulfillment_data`: `slug, listing_id, tradelink, market_hash_name, phase,
expected_units (listing price), float_value`.
- Line label «<name> · <wear>».
- Tests: happy path; guest → 401; other-account link → 422; gone listing → 422 with
  `next_offer`; price drift inside/outside tolerance; hidden keys absent from the customer
  order response; saved trade link written on successful checkout.

### Task 4: Waxpeer buy + status client

**Files:** modify `waxpeer_client.py`.

- `buy_one_p2p(*, item_id, price_units, partner, token, project_id) -> WaxpeerBuy(id, price)`
  (`success:false` → `WaxpeerBuyRefused(msg, new_price)`), `check_project_ids(ids) ->
list[WaxpeerTrade]` (≤ 100 ids per call), `WaxpeerTrade` dataclass with the spike's fields.
- Tests (respx): parse the spike's recorded bodies (§8.1) for statuses 0, 2, 4, 4+release, 6;
  refusal with `new_price`; transport error → `WaxpeerUnavailableError`.

### Task 5: The skin fulfiller

**Files:** Create `fulfillment/suppliers/waxpeer_skins.py`; modify `waxpeer.py`
(`fulfill`/`check_status` branch on `mapping.kind == "skin"`), `base.py` docs only.

- `fulfill_skin`: lookup `project_id` first (a replay after a crash); else `buy_one_p2p` at
  `expected_units`. Refused (sold/price up) → re-read live listings for the name, buy the
  cheapest `auto` listing with `price ≤ expected_units` (same float band not required),
  at most 2 substitutions; none → `failed`, `RETURNED`. Transport error on buy →
  `in_progress` id-less with `project_id` in metadata (lookup resolves it; after 10 min
  unresolved → `failed`, `UNKNOWN`, alert). Low balance message → the existing soft
  low-balance path. Creates/updates the `skin_trades` row.
- `skin_status`: map per Global Constraints; `succeeded` artifact
  `topup_receipt` with `kind:"skin"`, `name`, `trade_id`, `release_date`, `accepted_at`;
  schedules the next check (`schedule_next_check`) at 5 s while status ∈ {0,1,2}, 10 s at 4.
- Tests (unit + integration with respx): success path 0→2→4→4+release → delivered; sold →
  substitute; no substitute → failed RETURNED; lost response → lookup adopts, no second buy;
  6 before accept → failed RETURNED; low balance → soft; `skin_trades` row mirrors each step.

### Task 6: Sweeps

**Files:** Create `apps/scheduler/.../jobs/skins_trades_reconcile.py` (every 5 s,
`due_reconcile_task_ids(supplier="waxpeer")` filtered to skin tasks, batched
`check_project_ids`), `jobs/skins_protection_watch.py` (hourly: `skin_trades` with status 4,
`release_date` set, not released → refresh; 5 → mark released; 6 with `penalties` → alert
«откат скина», record `SPENT` on the task metadata, no customer action). Modify
`jobs/waxpeer_reconcile.py` to skip skin tasks (one owner per task). Register both.

- Tests: due selection; batching; protection 5 and 6+penalties paths; waxpeer_reconcile
  ignores skin tasks.

### Task 7: Automatic refund to the wallet

**Files:** Create `payments/refund_to_wallet.py`; modify `fulfillment/service.py` (after a
skin task fails with `RETURNED`, in both `_apply_failure` and `process_webhook_update`),
`wallet/README.md`, ADR-0093 (money section).

- `refund_order_to_wallet(db, *, order_id, reason) -> None`, idempotent on
  `refund:{payment.id}` (the same key `refund_admin` uses, so the two can never both run):
  - paid externally → `D user_wallet:<user>` / `C provider_clearing:<provider>` (the order
    payment becomes a balance top-up; no acquirer call);
  - paid from the wallet → `D user_wallet` / `C house_payments_received` (the `refund_admin`
    inverse);
  - payment → `refunded` with `metadata.refunded_to = "wallet"`, order → `refunded`, a
    customer notification (bot message if Telegram-linked; the order page shows it).
- Only for skin tasks and only on `RETURNED`; `UNKNOWN`/`SPENT` alert as today.
- Tests: card-paid and wallet-paid postings balance; replay/double trigger posts once;
  `refund_admin` after it → conflict; UNKNOWN does not refund.

### Task 8: Order API — trade progress for the buyer

**Files:** modify `orders/schemas.py` (`OrderItemOut.skin_trade: SkinTradeOut | None`),
`orders/service.py` (join `skin_trades`), `docs/api/openapi.json` via `make gen-api`.

- `SkinTradeOut`: `state` (`buying | offer_sent | accepted | released | failed`),
  `offer_url` (`https://steamcommunity.com/tradeoffer/{trade_id}/`), `send_until`,
  `release_date`, `seller {name, avatar_url, level, joined_at}`, `reason_code`
  (`not_accepted | sold_out | other`).
- Tests: each state from a `skin_trades` row; another user's order → 404 as today; N+1 guard
  (query count) on the orders list.

### Task 9: Docs

- `docs/product/flows/skins-buy.md` (sequence diagram), `docs/architecture/sequence-diagrams/
skins-purchase.mmd`, `docs/runbooks/skins-purchase.md` (fund Waxpeer, low-balance alert,
  rollback alert, manual card refund on request), `docs/security/threat-model.md` +
  `pii-handling.md` (trade link token), module README, AGENTS §9/§10 lines, ADR-0093 amendment.
