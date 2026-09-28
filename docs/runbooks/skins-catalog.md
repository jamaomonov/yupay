# Runbook: CS2 skins catalogue

The catalogue behind `/skins/*` (ADR-0093): `skin_items` rows imported daily from
ByMykel/CSGO-API, Waxpeer prices folded on every five minutes from the CSV snapshot.
Purchase is not built yet; this runbook covers the catalogue only.

## Is the sync running?

```bash
docker compose -f docker-compose.prod.yml logs --since 15m scheduler | grep skins.prices.synced
```

Expect one line per five minutes with `names≈24000` and `changed` in the hundreds. The
daily import logs `skins.import.done files=11 rows≈35000`.

A `skins.prices.skipped` / `skins.import.skipped` line means `CS2_SKINS_SYNC_ENABLED` is
false or `WAXPEER_API_KEY` is empty — both jobs do nothing until both are set.

## The snapshot fails

`skins.prices.failed` with the Waxpeer error. Prices stand as they were; `prices_updated_at`
stops moving:

```sql
SELECT max(prices_updated_at) FROM skin_items;
```

Older than 30 minutes: check Waxpeer's status, the key (`GET /v1/user`), and the scheduler
container's memory — the snapshot is ~240 MB of text streamed per tick and must never be
read whole.

## A row with no image

`source = 'stub'` rows exist because the snapshot named an item ByMykel has not caught up
with (a new case, a new sticker). The next daily import fills them. To run it now, from a
scheduler shell:

```bash
docker compose -f docker-compose.prod.yml exec scheduler \
  python -c "import asyncio; from yupay_scheduler.jobs.skins_catalog_import import run_skins_catalog_import as r; asyncio.run(r())"
```

## The item page says `degraded`

The listings read answered from a stale cache or the snapshot instead of live Waxpeer:
either the per-minute budget is spent or the breaker is open.

```bash
redis-cli GET skins:wax:breaker
redis-cli --scan --pattern 'skins:wax:budget:*'
```

The breaker clears itself after two minutes. A budget that is always spent means traffic
has outgrown the 20/min non-partner search limit — ask Waxpeer for partner status, then
raise `CS2_SKINS_LISTINGS_BUCKET_PER_MINUTE`.

## Opening the storefront

1. `CS2_SKINS_SYNC_ENABLED=true`, restart the scheduler.
2. Wait for one import (`skins.import.done`) and one price tick (`skins.prices.synced`).
3. Check prices in the admin preview (`GET /admin/skins/pricing/preview`).
4. `CS2_SKINS_ENABLED=true`, restart the api.

## Adding a search alias

```sql
INSERT INTO skin_search_aliases (alias, text) VALUES ('авп', 'awp')
ON CONFLICT (alias) DO UPDATE SET text = EXCLUDED.text;
```

Cached suggest pages expire within 60 s.
