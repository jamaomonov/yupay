# Google Merchant Center feed

Hourly scheduler job `integrations.merchant_feed` pushes every active
fixed-price SKU into Merchant Center (account 5833475365, data source
«api v2» / 10718106908) over the Merchant API, and deletes what we no longer
sell. Design: ADR-0065. The job runs right after the price refresh and the
catalog watchdog, so Google carries the numbers those ticks just wrote.

## Configuration (prod `secrets/api.env` + a key file)

```
MERCHANT_CENTER_ACCOUNT_ID=5833475365
MERCHANT_CENTER_DATA_SOURCE_ID=10718106908
MERCHANT_CENTER_KEY_FILE=/run/secrets/merchant-center.json
```

The key file is a Google Cloud **service account** JSON key; the service
account's email must be added in Merchant Center under Настройки → «Люди и
доступ» (admin). Mount the file into the scheduler container (compose
`volumes:` entry next to the env_file). While any of the three settings is
empty the job logs `skipped="not configured"` and does nothing.

## Liveness and diagnosis

- Log line per tick: `integrations.merchant_feed.tick` with
  `desired/upserted/deleted/skipped/errors`.
- `skipped` counts SKUs we chose not to feed (variable-amount, no image, no
  resolvable price this tick) — a nonzero value is normal.
- `errors` > 0 → per-item `upsert_failed`/`delete_failed` warnings carry the
  offer id and Google's message. Google-side refusals (policy, image
  quality) live in Merchant Center → Товары → Диагностика; they are
  per-item and do not block the rest of the feed.
- Google's digital-goods moderation can refuse items or, worst case, the
  account. If the whole feed goes `errors == desired`, check the account
  status banner in MC before debugging our side.

## Removal semantics

Deletion is reconciled against the account's own product list every tick, so
a SKU deactivated by the catalog watchdog (or by hand) leaves Google on the
next tick even if the feed was down when it happened. Deleting an
already-absent product is treated as success.
