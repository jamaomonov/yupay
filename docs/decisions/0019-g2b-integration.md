# 0019. G2Bulk (G2B) supplier integration

- **Status**: Accepted
- **Date**: 2026-05-27
- **Deciders**: @jamaomonov
- **Tags**: backend | integrations | fulfilment

## Context and problem statement

YuPay has a complete fulfilment skeleton (ADR-0013, ADR-0015) but no real
supplier wired up — only `mock`, `manual`, and a handful of `_stub.py`
slugs. The business needs to start fulfilling real orders against an
external vendor. The chosen first supplier is **G2Bulk** (`api.g2bulk.com`),
which covers two flows we care about: pre-paid digital vouchers (game
codes, gift cards) and live game top-ups (PUBG UC, MLBB diamonds, Free Fire,
~180 games total).

The integration must:

1. Slot into the existing `Fulfiller` protocol without forcing changes to
   the saga or the FSM.
2. Be controllable from the admin UI (health, mapping, attempt log,
   catalog sync) — not just by editing the database.
3. Survive G2B's two-mode delivery model (synchronous voucher with
   optional polling; asynchronous game top-up with webhook callbacks).
4. Not leak the API key, customer player IDs, or voucher codes into logs.

## Decision drivers

- **No FSM changes.** The saga in `fulfillment.service` already supports
  `succeeded`/`in_progress`/`failed` outcomes — async fulfilment is already
  modelled, we just need to plug the wire in.
- **Future-proof against more suppliers.** Steam, Riot, PUBG-direct,
  Spotify, Apple are already reserved slugs (`fulfillment/suppliers/_stub.py`).
  Whatever we build for G2B should be a template, not a special case.
- **No multi-tenant credential storage yet.** Single-account env-only is
  the cheapest option now; a `supplier_credentials` table is a future sprint
  triggered by a real "we need two G2B accounts" use case.
- **Security.** G2B itself bans the IP on repeated 401s and doesn't sign
  webhooks. Authentication of incoming webhooks must come from a
  random-token secret in the URL path, and we must always re-verify the
  order via `GET /v1/orders/:id/delivery` / `POST /v1/games/order/status`
  before mutating any task state.

## Considered options

1. **One adapter per G2B flow** (`g2b_voucher`, `g2b_game` as separate
   slugs) — duplicates the HTTP client, the auth handling, the redactors;
   forces the admin to choose the right flow in the sourcing UI even though
   the SKU's kind already tells us which one to use.
2. **One unified `G2bFulfiller` adapter** that switches between the
   voucher and game branches inside `fulfill()` based on the mapping row.
3. **JSONB column on `sku_sourcing_rules`** for the external product id,
   instead of a new table — keeps the schema smaller but conflates
   routing ("send to G2B") with mapping ("what to ask G2B for").
4. **New `sku_supplier_mapping` table** (composite PK
   `(sku_id, supplier_slug)`) — clean separation of routing from mapping,
   ready for fallback chains, easy to query by external id for webhook
   correlation.

## Decision outcome

**Chosen options:**

- **Option 2** for the adapter shape (one `G2bFulfiller`, two branches).
- **Option 4** for the mapping persistence (new `sku_supplier_mapping`
  table).

Plus three supporting decisions:

- API key in `G2B_API_KEY` env var (single account, multi-tenant later).
- Webhook secret in URL path: `POST /api/v1/webhooks/g2b/{secret}`. Body
  payload is **never trusted** — every webhook triggers a fresh status
  re-fetch through the adapter before any state mutation.
- A backup for lost/absent webhooks. **Superseded (2026-08):** the originally
  planned per-order dramatiq polling actor (`g2b_polling.py`) was never wired up
  (nothing kicked off the first poll) and has been removed. The backup is now
  the `g2b_reconcile` scheduler sweep — every 60s it reconciles all `in_progress`
  g2b tasks through the same `process_webhook_update` path, mirroring
  `waxpeer_reconcile`. See `docs/runbooks/g2b-troubleshooting.md`.

### Positive consequences

- Adding Steam/Riot/etc. later is a copy-paste of `g2b.py` and one line in
  `REGISTRY`.
- `sku_supplier_mapping` lets us list "every SKU mapped to G2B" or
  reverse-lookup "this G2B external order id belongs to which YuPay SKU"
  cheaply via `ix_sku_supplier_mapping_lookup`.
- Same `task.id` flows end-to-end as `X-Idempotency-Key` to G2B — admin
  retry is automatically idempotent within G2B's 30-minute window.
- Webhook handler is short and dumb: validate secret, look up task by
  `external_order_id`, call `check_status()`, route through the same
  `process_webhook_update()` helper that the polling actor uses.

### Negative consequences

- One env var per credential field — operationally noisier than a single
  secrets table. We accept this until multi-tenant pressure shows up.
- Catalog sync (`supplier_catalog_cache`) is best-effort and may go stale;
  the admin needs to refresh manually. Acceptable: it's only used for
  autocomplete, not for the live fulfilment path.
- The polling actor needs explicit termination logic (30-minute ceiling)
  to avoid a stuck task pinging G2B forever.

## Validation

- **Tests.** Sprint B ships ≥ 95% coverage on `suppliers/g2b.py` and the
  webhook route; integration tests assert "PENDING voucher → polling →
  succeeded" and "game order → webhook → succeeded" end-to-end.
- **PII redaction.** Unit test confirms `g2b_api_key`, `delivery_items`,
  and `player_id` never appear in structured logs.
- **Manual prod smoke.** After deploy: create one test SKU mapped to a
  cheap G2B voucher, place an order through the miniapp, verify a code is
  delivered and the FulfillmentAttempt log shows the redacted G2B
  interaction.

## References

- ADR-0013 — Fulfilment skeleton and provider stubs.
- ADR-0015 — Inventory + sourcing skeleton.
- `docs/g2b-intergation.md` — G2B API reference.
- `docs/runbooks/g2b-troubleshooting.md` (added in Sprint B).
