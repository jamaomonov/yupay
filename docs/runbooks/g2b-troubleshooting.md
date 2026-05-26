# Runbook — G2B (G2Bulk) integration

## Symptoms → diagnosis

| Symptom (admin sees)                                                                         | Likely cause                                | First action                                                                                                           |
| -------------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `/admin/integrations/g2b/health` → `available: false, reason: G2B_API_KEY is not configured` | Env var missing in `api.env`                | Add `G2B_API_KEY=…` to `/opt/yupay/secrets/api.env`, then `docker compose up -d --force-recreate api worker scheduler` |
| `available: false, reason: g2b HTTP 401`                                                     | Wrong / revoked / banned key                | **STOP making calls** — repeated 401s permanently ban our IP. Get a fresh key via the G2B Telegram bot                 |
| `available: true, balance: 0`                                                                | Pre-paid wallet empty on G2B side           | Top up the G2B account via their Telegram bot                                                                          |
| Task stuck `in_progress` after ~10 min, no webhook                                           | Webhook never reached us                    | See "Webhook lost" below                                                                                               |
| Task `failed`, `last_error: g2b purchase failed: HTTP 410`                                   | Order was refunded / cancelled on G2B side  | Refund the customer via `/admin/payments/{id}/refund`; the G2B balance was already returned automatically              |
| Task `failed`, `last_error: no active g2b mapping for SKU`                                   | Missing or `is_active=false` mapping        | Create the mapping at `/admin/integrations/mappings`                                                                   |
| Game task `failed`, `last_error: missing fulfillment_data.player_id`                         | Customer didn't enter player_id at checkout | Refund + ask product team why the form let the order through                                                           |

## Webhook lost — manual reconciliation

If a task is stuck `in_progress` and you suspect the webhook never fired:

1. Confirm `g2b_callback_url` env var matches what's actually publicly
   reachable (`curl -X POST $G2B_CALLBACK_URL`). Behind Cloudflare /
   Caddy a wrong URL = silent failure.
2. Hit `POST /api/v1/admin/fulfillment/tasks/{task_id}/retry` — this
   replays `fulfill()` against G2B with the same `X-Idempotency-Key`
   (= `task.id`), which means within 30 minutes G2B returns the same
   order; outside of 30 min G2B may create a duplicate. Prefer to
   resolve within the window.
3. If the task is past the idempotency window, the safer path is
   `/cancel` the task locally and refund the customer; do not let the
   adapter create a second G2B order.

## Webhook poisoning attempt

A 404 in API logs at `/api/v1/webhooks/g2b/*` means someone hit the
endpoint with the wrong secret. Verify nothing leaked the real
`G2B_WEBHOOK_SECRET` (audit recent `secret-rotation-log.md` entries).
If a leak is suspected, rotate:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# update /opt/yupay/secrets/api.env: G2B_WEBHOOK_SECRET + G2B_CALLBACK_URL
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
