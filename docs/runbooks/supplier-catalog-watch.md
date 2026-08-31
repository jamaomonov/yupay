# Supplier catalog watchdog

The hourly scheduler job `integrations.catalog_watch` compares every **active**
supplier mapping against the supplier's live catalogue and takes delisted
positions off the shelf. A supplier can delete a SKU at any moment for no
stated reason — rotating promo packs, «(discounted)» variants, withdrawn
vouchers — and before this job existed the first signal was a customer's
failed order.

## What it does

| Event                                       | Action                                                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Mapped position missing (1st time)          | Stamps `extra.catalog_missing_since` on the mapping. Nothing visible changes.                                  |
| Still missing on a later tick (≥ 45 min)    | Deactivates the SKU (`skus.active=false`), marks the mapping, sends one Telegram alert (`kind=catalog_watch`). |
| Supplier fetch error / empty game catalogue | Skips that game entirely — no stamps. An outage must not mass-deactivate the shelf.                            |
| Position reappears before deactivation      | Clears the stamp quietly.                                                                                      |
| Position reappears after deactivation       | Telegram alert; the SKU **stays off** — a human re-checks the price and re-enables it in the admin SKU card.   |

Game mappings are checked against `games_catalogue` names (one supplier call
per distinct game), voucher mappings via `fetch_product` by id (`None` is the
supplier's explicit "not listed"; an exception is not a miss). The mapping row
itself always stays active — it is the watch's memory.

## Where

- Logic: `apps/api/src/yupay/modules/integrations/catalog_watch.py`
- Job: `apps/scheduler/src/yupay_scheduler/jobs/catalog_watch.py`, same cadence
  as the catalog sync/price refresh (`PRICE_REFRESH_INTERVAL_MINUTES`), first
  run +180s so it reads the state those jobs just acted on.
- Alerts go to the ops chat via `notifications.send_admin_alert`
  (`TG_ALERT_BOT_TOKEN` / `TG_ALERT_CHAT_ID` in `secrets/api.env`).

## Operator notes

- Liveness: `integrations.catalog_watch.tick` log line each interval with
  `checked/stamped/deactivated/reappeared/skipped_games`.
- After a «position reappeared» alert: check the supplier price in the mapping
  picker, then re-enable the SKU in the admin (Каталог → SKU → активность).
  Re-enabling does not clear anything — the watch only stamps again if the
  position goes missing again.
- False deactivation (supplier API changed its naming, not its assortment):
  re-enable the SKU and fix the mapping's `external_variant_id` to the new
  name; the old name will never match again and would just re-deactivate.
- Currently wired for G2B. Another supplier needs its client to expose
  `games_catalogue`/`fetch_product` (the `CatalogClient` protocol) and a
  branch in the job; the two-strike logic is supplier-agnostic.
