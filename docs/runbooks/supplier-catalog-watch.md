# Supplier catalog watchdog

The hourly scheduler job `integrations.catalog_watch` compares every **active**
supplier mapping against the supplier's live catalogue and takes delisted
positions off the shelf. A supplier can delete a SKU at any moment for no
stated reason — rotating promo packs, «(discounted)» variants, withdrawn
vouchers — and before this job existed the first signal was a customer's
failed order.

## What it does

| Event                                       | Action                                                                                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Mapped position missing (1st time)          | Stamps `extra.catalog_missing_since` on the mapping. Nothing visible changes.                                                          |
| Still missing on a later tick (≥ 45 min)    | Marks the mapping delisted and sends one Telegram alert (`kind=catalog_watch`). What happens to the SKU: see below.                    |
| Supplier fetch error / empty game catalogue | Skips that game entirely — no stamps. An outage must not mass-deactivate the shelf.                                                    |
| Position reappears before deactivation      | Clears the stamp quietly.                                                                                                              |
| Position reappears after it was confirmed   | Telegram alert. A SKU that went off **stays off** until a human re-checks the price; a route that moved does not move back on its own. |

### What a confirmed delisting does to the SKU

One supplier dropping a position is not the SKU becoming unsellable. Until
2026-09-25 it was treated as if it were: G-Engine dropped six Blood Strike
packs, five of those SKUs were routed to FazerCards, all six were still
carried by G2B, FazerCards and NOVA — and every one came off the shelf. So the
confirmation now asks where the SKU is bought (`catalog_watch_settle.py`):

| The supplier that delisted it is…                  | What happens                                                                                                                                                  |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| not the SKU's route                                | Nothing on the shelf. The mapping is marked so routing never picks it again. Alert: «покупается через X — на витрине ничего не меняется».                     |
| the route, and another non-reserve mapping is live | The SKU moves there. A `force_supplier` rule naming the delisted supplier is dropped so auto routing takes over, and the SKU is re-priced at once (ADR-0091). |
| the route, and only reserves (or nothing) remain   | The SKU goes off, as before. Reserves are never reached automatically (ADR-0081): the alert names them so a person can force the SKU there.                   |

The mark is `extra.catalog_watch_deactivated` (`integrations.models.CATALOG_DELISTED`).
The mapping itself stays `is_active` — it is the watch's memory, and how it
notices the position coming back — so auto routing reads the mark too.

**The mark must survive the hourly price refresh.** Until the same day, the
refresh snapshotted every mapping and `session.merge`d each snapshot back,
which wrote a minutes-old `extra` over the row. The watch runs 90 s into that
pass, so its mark was wiped behind it and the same SKUs were switched off and
re-alerted every hour. The refresh now re-reads each row instead. If a
"deactivated" alert ever repeats hourly for the same SKU, look there first.

## Which suppliers, and how each is asked

All three that need a mapping. They are asked differently because they answer
differently:

| Supplier | Entry point             | How "still listed?" is answered                                                                               |
| -------- | ----------------------- | ------------------------------------------------------------------------------------------------------------- |
| G2B      | `watch_mapped_variants` | Live: `games_catalogue` names per game; vouchers via `fetch_product` by id.                                   |
| NOVA     | `watch_cached_variants` | `run_game_denomination_sync` refreshes the game, then the mapping is diffed against `supplier_catalog_cache`. |
| G-Engine | `watch_cached_variants` | Same as NOVA.                                                                                                 |

### What the watch does **not** cover: NOVA and G-Engine gift cards

The watch reads `kind='game'` mappings for NOVA and G-Engine, and G2B's flat
vouchers. Since ADR-0090 those two suppliers also carry **voucher** mappings
with a ladder under them — NOVA gift-card cards, G-Engine shop denominations
— and no watch tick looks at them. That is a real gap, recorded here rather
than left to be rediscovered.

What does cover the customer-facing half: the hourly voucher stock sweep
(`integrations/stock_refresh.py`) writes `supplier_stock = 0` for a `card_id`
or shop denomination that has vanished from its parent, so the SKU stops being
buyable within the hour without anyone doing anything. What is missing is the
rest of the watch's behaviour — the two-strike stamp, `skus.active=false`, and
the Telegram alert. So a delisted gift card goes quiet rather than announced.

Closing it means teaching `watch_cached_variants` the voucher kind and
pointing it at `run_voucher_denomination_sync`, which already exists.

### A denomination missing from the mapping picker

Two different causes, and they look identical from the admin:

1. **The supplier stopped listing it.** Then the watch has already stamped
   the mapping, or deactivated the SKU and said so in the ops chat.
2. **Another game took the row.** Until migration 0084 the cache key was
   `(supplier_slug, kind, external_id)`, which assumed a denomination id is
   unique across a supplier's whole catalogue. It is not: NOVA calls the
   55-diamond pack `55_diamonds` in Magic Chess Go Go (RU) and in Mobile
   Legends (RU) alike, so the two games shared one row and each sync stole it
   from the other. Measured on production 2026-09-19: NOVA returned 17 offers
   for `magic_chess_gogo_ru` and the cache held 9, the other eight sitting
   under `mobile_legends_ru`. `parent_external_id` is part of the key since
   0084, so this cause is closed — if a denomination is missing now, it is
   cause 1.

The cached path works **only because the denomination syncers prune** — see
`integrations.service.prune_catalog_denoms`. Before it existed they upserted
and never deleted, so a withdrawn pack stayed cached forever. If that pruning
is removed, the NOVA/G-Engine watch does not fail; it silently stops finding
anything. `test_cached_watch_sees_nothing_without_pruning` pins that.

An empty pass never prunes and never stamps: a sync that errors, writes
nothing, or leaves the cache empty skips that game. The same rule as G2B's
empty catalogue, for the same reason.

Two kinds of mapping are skipped before any call is made, because nothing
about them could be missing from a denomination list:

- the NOVA Steam reserve sentinel (`steam-topup`), which is not a catalogue
  category at all (ADR-0082 §4) and answers 404 every time;
- **amount-priced** mappings — the Steam wallet, Telegram Stars — which buy a
  sum rather than a listed pack and so carry no `external_variant_id`.

Both were found by the first production tick, which logged a warning for
G-Engine services 2 and 72 before it was taught to leave them alone.

The mapping row itself always stays active — it is the watch's memory. It is
**not** deleted on a deactivation: that is deliberate, because the mapping is
how a reappearance is recognised, and because a human needs to see what the
SKU used to point at before re-enabling it.

Until 2026-09-19 only G2B was watched. That was tolerable while it held almost
every mapping, and stopped being tolerable when NOVA and G-Engine went from 63
mappings between them to 241.

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
- Each supplier runs in its own session and its own `try`, so one supplier's
  outage cannot roll back stamps another already wrote, and the tick log line
  carries `supplier=`.
- A fourth supplier joins one of the two paths: a live client satisfying the
  `CatalogClient` protocol, or an entry in `DENOM_SYNCABLE_SUPPLIERS` whose
  syncer prunes. The two-strike logic is supplier-agnostic either way.
- NOVA and G-Engine normally cost **no** supplier calls: `sync_supplier_catalog`
  refreshes exactly these games 120s earlier on the same cadence, and the watch
  reads what it wrote. A game whose oldest cached row is more than 30 minutes
  old is fetched here instead — that means the sweep did not run or did not
  reach it, and judging a mapping against hour-old rows is how a delisting gets
  missed or invented. The tick logs
  `integrations.catalog_watch.denoms_refetched` with a count when that happens;
  a steady non-zero count there means the sweep is unhealthy, not this job.
- Before 2026-09-20 the watch always fetched: 14 NOVA categories and 13
  G-Engine services per tick, 27-40 calls an hour, and G-Engine's per-game sync
  re-walks its whole services list every time.
