# Runbook — G2B (G2Bulk) integration

## Symptoms → diagnosis

| Symptom (admin sees)                                                                         | Likely cause                                | First action                                                                                                |
| -------------------------------------------------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `/admin/integrations/g2b/health` → `available: false, reason: G2B_API_KEY is not configured` | Env var missing in `api.env`                | Add `G2B_API_KEY=…` to `secrets/api.env`, then `docker compose up -d --force-recreate api worker scheduler` |
| `available: false, reason: g2b HTTP 401`                                                     | Wrong / revoked / banned key                | **STOP making calls** — repeated 401s permanently ban our IP. Get a fresh key via the G2B Telegram bot      |
| `available: true, balance: 0`                                                                | Pre-paid wallet empty on G2B side           | Top up the G2B account via their Telegram bot                                                               |
| Task stuck `in_progress` after ~10 min, no webhook                                           | Webhook never reached us                    | Auto-recovered by the `g2b_reconcile` sweep (every 60s); see "Webhook lost" below                          |
| Game task stuck `in_progress` **though the credit reached the player**, webhook logged `g2b.webhook.unknown_order` | `external_order_id` was persisted as the string `"None"` (pre-fix response-parsing bug) — the flat webhook can't match it | See "Mis-stored external_order_id" below |
| Task `failed`, `last_error: g2b purchase failed: HTTP 410`                                   | Order was refunded / cancelled on G2B side  | Refund the customer via `/admin/payments/{id}/refund`; the G2B balance was already returned automatically   |
| Task `failed`, `last_error: no active g2b mapping for SKU`                                   | Missing or `is_active=false` mapping        | Create the mapping at `/admin/integrations/mappings`                                                        |
| Game task `failed`, `last_error: missing fulfillment_data.player_id`                         | Customer didn't enter player_id at checkout | Refund + ask product team why the form let the order through                                                |

## Webhook lost — reconciliation

G2B's webhook fires **once with a single retry and a 10s timeout**, so a cold
start / redeploy / transient 5xx on our side loses it for good. Two safety nets:

- **Automatic:** the `g2b_reconcile` scheduler job sweeps every `in_progress`
  g2b task every 60s and re-verifies it via `POST /games/order/status` (the same
  `process_webhook_update` path a real webhook takes). A lost webhook self-heals
  within a minute — no action needed. Confirm it's running: look for
  `g2b_reconcile.tick` / `g2b_reconcile.registered` in the scheduler logs.
- **Manual (only if the sweep can't):**
  1. Confirm `g2b_callback_url` matches what's publicly reachable
     (`curl -X POST $G2B_CALLBACK_URL`). Behind Cloudflare / Caddy a wrong URL =
     silent failure.
  2. `POST /api/v1/admin/fulfillment/tasks/{task_id}/retry` only accepts
     `failed`/`pending` tasks — it **rejects `in_progress`** (409 Conflict). For
     a stuck `in_progress` task, let the sweep reconcile it; do **not** re-run
     `fulfill()` (that risks a duplicate G2B order outside the 30-min
     idempotency window).
  3. If genuinely unrecoverable, `/cancel` the task locally and refund the
     customer.

## Mis-stored external_order_id (`"None"`)

**Root cause (fixed):** G2B wraps order data under an `order` key
(`{"success": true, "order": {"order_id": …, "status": …}}`) in the `create`
and `games/order/status` responses — but the webhook body is *flat*. An early
`g2b_client` read `order_id`/`status` off the top level, so it stored
`external_order_id="None"` and treated every game order as `pending`. The flat
webhook (`order_id: 1309981`) then logged `g2b.webhook.unknown_order` and the
task stranded in `in_progress` even though the player was already credited.
Fixed by `_unwrap_order()` in `g2b_client.py` (unwraps `order` when present,
falls back to flat).

**Repairing a task stranded before the fix** (the `g2b_reconcile` sweep can't —
it would call status with `order_id="None"`):

1. Find the real G2B order id from history — it echoes our `remark`
   (`yupay:<order_item_id[:8]>`):
   ```bash
   curl -s "$G2B_BASE_URL/games/orders?limit=50" -H "X-API-Key: $G2B_API_KEY"
   ```
2. Point the task at it, then let the next sweep (≤60s) complete it:
   ```sql
   UPDATE fulfillment_tasks
      SET external_order_id = '<real_order_id>', updated_at = now()
    WHERE supplier = 'g2b' AND status = 'in_progress' AND external_order_id = 'None';
   ```

## Webhook poisoning attempt

A 404 in API logs at `/api/v1/webhooks/g2b/*` means someone hit the
endpoint with the wrong secret. Verify nothing leaked the real
`G2B_WEBHOOK_SECRET` (audit recent `secret-rotation-log.md` entries).
If a leak is suspected, rotate:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# update secrets/api.env: G2B_WEBHOOK_SECRET + G2B_CALLBACK_URL
docker compose up -d --force-recreate api worker scheduler
```

Then place a tiny no-fulfilment test order to confirm the new callback
URL reaches us. Rotation invalidates any in-flight game orders that
G2B still has the old URL for — those will appear as "task stuck", use
the manual reconciliation above.

## 429 from G2B

The G2bClient already retries with exponential backoff (1s, 2s, 4s, 8s)
on 429 and 5xx. If we're consistently hitting 429:

- Check the `g2b.request` log volume on the api / worker container —
  someone is hammering the polling actor or an admin is clicking
  "Refresh health" in a loop. The health probe is cached for 30s in the
  fulfiller itself; if the cache isn't working, that's a bug.
- Rate limit is 1000 req / 10 sec per key. We don't approach this in
  normal traffic; a sudden spike means something is wrong.

## Catalog drift

`POST /api/v1/admin/integrations/g2b/sync-catalog` populates
`supplier_catalog_cache`. The cache is only used as autocomplete in the
admin UI — never in the live fulfilment path. So a stale cache can't
cause an order to fail, only annoy an admin. Re-run sync as needed.

## Related

- ADR-0019 — G2B integration design.
- `docs/g2b-intergation.md` — full G2B API reference.
- `docs/architecture/sequence-diagrams/g2b-voucher.mmd`, `g2b-game.mmd`.
- `docs/runbooks/supplier-api-down.md` — generic supplier-outage drill.
