# Design: CS2 skins, bought on Waxpeer and delivered to the customer's Steam

**Date:** 2026-09-28
**Status:** Approved in chat — the delivery model, the catalogue source, the "show the seller and
the inspect link" call and the ready-gate are the owner's, recorded in §2
**Branch:** `feat/cs2-skins`
**Builds on:** ADR-0066 (Steam Gifts: live prices, dynamic checkout, adopt-don't-rebuy),
ADR-0064 (work reaches the worker as rows), the existing `waxpeer` supplier (Steam wallet top-ups)
**Surface:** API (`modules/skins`, `fulfillment/suppliers/waxpeer*`), scheduler, worker, web,
miniapp, admin
**New ADR:** 0093

---

## 1. Problem

Customers ask for CS2 skins. Waxpeer — the supplier we already pay Steam top-ups through — sells
them by API: ~1.19 million listings across ~23 900 market names, priced in integer units
(`1000 = $1`), bought with one call and delivered as a Steam trade offer to any trade link.

A skin is not a top-up. A listing is one physical item that someone else can buy first; delivery
needs the customer to accept a trade offer in Steam; a trade can sit in a Steam hold for days and
roll back; and a rollback that is the buyer's fault costs the buyer — us — a 30 % penalty and a
mark on the account that can suspend our P2P purchasing. The design below is mostly about those
four facts.

Everything numeric in this document was measured against the live API with our key on
2026-09-28 (see §10).

## 2. Decisions taken by the owner

1. **Deliver straight to the customer's trade link.** No Steam bot of our own: it would add a
   7-day trade cooldown to every skin we touch (CS2 locks items received by trade), tie capital
   up in inventory, and the customer would still have to accept an offer.
2. **Our catalogue is ours.** Names, taxonomy, images and slugs come from an independent source
   (ByMykel/CSGO-API, §4); Waxpeer supplies only listings — id, price, float, stickers,
   `auto` — joined by market hash name. Nothing that reaches a browser is Waxpeer-branded:
   images are Steam's own CDN, listing ids are Steam asset ids.
3. **Show the seller and the inspect link.** The seller's name, avatar, level and join date on
   the order page so the customer recognises the incoming offer; "Inspect in game" on every
   listing. Both reveal the seller's Steam identity; that is true of every P2P market and is
   accepted.
4. **Buy only `auto` listings.** 94 % of the market (96 % under $20). Manual sellers and
   trade-locked ("hold") listings are never offered.
5. **Skin names stay English; the structure is localised.** Categories, weapons, wear and the
   StatTrak/Souvenir flags get RU/EN/UZ labels from a hand-kept table; "Redline" is "Redline"
   in every locale. No Russian localisation of item names exists in the open any more (§4.3),
   and that is how the market people buy from already works.
6. **The Waxpeer purchase happens when the customer says they are ready**, not at payment.
   Money is taken at payment as usual; the order page then shows «Я готов принять обмен», and
   the buy call goes out on that tap. This exists to cut "Buyer failed to accept" rollbacks,
   which are ours to pay for (§6.4). Unconfirmed after a configurable window → refund.

## 3. Shape of the Waxpeer buy side (what the API actually does)

- **Listings** carry an undocumented but live `auto: bool` and `delivery: "bot" | "p2p"`
  on `GET /v2/search-items-by-name?delivery_details=1`; the documented source of `auto` is
  the CSV snapshot (`GET /v1/prices/snapshot?format=csv`, one row per listing, refreshed every
  15 s). `bot` is Waxpeer's own inventory, `p2p` + `auto` is an automated seller; both deliver
  in seconds to minutes. Waxpeer auto-cancels a trade that never gets created after 6 min, one
  waiting for the seller's mobile confirm after 11–15 min, and one whose seller vanished after
  6 h.
- **Buying:** `POST /v1/buy` (bulk, one trade link) or `GET /v1/buy-one-p2p` (one item). We pass
  `item_id`, `price` (the purchase is refused with `new_price` if the price rose — this is our
  drift guard), `partner`/`token` from the trade link, and `project_id` = our task id. A repeated
  call with the same `project_id` is **not** documented as deduplicated (unlike a top-up's
  `custom_id`), so a lost response is resolved by looking the trade up
  (`GET /v1/check-many-project-id`), never by buying again — the `gengine_gifts` rule.
- **Status** is a number on two axes: `0 processing → 1 creating → 2 seller confirm → 4 sent,
buyer can accept → 5 completed`, `6 declined/refunded`; plus `escrow_status`
  (`awaiting_unlock | sending | trade_sent | steam_hold | completed | failed | null`),
  `is_released`/`release_date` (the 7-day hold after the buyer accepts), `send_until` (the
  deadline for the buyer to accept), `trade_id` (the Steam offer id — deep-linkable as
  `https://steamcommunity.com/tradeoffer/{trade_id}/`), `seller_*`, `reason`, and `penalties`
  (`rollback_fee` 20 % + `rollback_penalty` 10 %, charged to the buyer on a buyer-fault
  rollback).
- **Push:** the Socket.IO endpoint (`wss://waxpeer.com/socket.io`, `authorization: <api key>`
  header) emits Steam-trade lifecycle updates to the buyer. The HTTP webhook
  (`POST /v1/update-account {webhook}`) is unsigned and undocumented for purchases; we do not use
  it. The trade websocket (`wss://wssex.waxpeer.com`) is for Steam-bot accounts and is not
  needed under decision 2.1.
- **Pre-checks:** `POST /v1/check-tradelink` (trade ban, private inventory, Steam's own reason
  in `info`); Steam's `IEconService/GetTradeHoldDurations` with our `steam_api_key` gives the
  escrow (hold) duration a trade to that link would get.
- **Rate limits:** search-by-name and mass-info share 20 requests/min for non-partner accounts;
  the CSV snapshot is 429 with `Retry-After: 1` when too many renders are in flight; nothing
  else is documented as limited. Partner status lifts the 20/min.

## 4. Catalogue

### 4.1 Source of items: ByMykel/CSGO-API

MIT, ~800 stars, a bot commits on every game manifest update (last: 2026-09-25). Per-wear
entries with `market_hash_name`, `weapon`, `category`, `pattern`, `rarity` (+ colour),
`min_float`/`max_float`, `stattrak`, `souvenir`, `paint_index`, `phase` (Doppler), and `image` —
a `community.akamai.steamstatic.com/economy/image/…` URL for 35 883 of 36 000 entries. Files:
`skins_not_grouped`, `stickers`, `agents`, `crates`, `keys`, `music_kits`, `graffiti`, `patches`,
`collectibles`, `keychains`, `highlights` under
`https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/`.

Against Waxpeer's 23 887 names: **22 962 match directly (96.1 %)**; rifles, SMGs, heavy, gloves,
agents, cases, keys, music kits and charms are 100 %. The 925 misses are 467 knives + 26 pistols
whose Waxpeer name carries a Doppler phase inline (`★ Karambit | Doppler Phase 2 (Factory New)`
vs ByMykel's `market_hash_name` `★ Karambit | Doppler (Factory New)` + `phase: "Phase 2"`), and
430 "Sticker Slab" items ByMykel does not carry. Normalising the phase out of the Waxpeer name
makes the match complete for everything we sell.

### 4.2 Our tables

`skin_items` — one row per `(market_hash_name, phase)`: slug, category (our taxonomy, §4.4),
weapon, skin, exterior, `stattrak`, `souvenir`, rarity + colour, `image_url` (Steam CDN),
float range, `paint_index`, `steam_price_units`; and the Waxpeer side — `min_auto_units`,
`count_auto`, `cheapest_auto` (JSONB, up to 10 `{item_id, price}`), `min_all_units`,
`count_all`, `price_hash`, `prices_updated_at`, `active` (= has at least one auto listing);
plus `search_text` with a trigram GIN index.

`skin_settings` — singleton (`id = 1`), like `steam_gift_settings`: `margin_percent`,
`price_floor_usd`. `skin_search_aliases` — `alias → text` ("ак" → "ak-47"), a small table that
grows from search logs.

### 4.3 Sync

- **Items, daily** (`skins_catalog_import`): fetch the eleven JSON files, parse, upsert
  metadata. A Waxpeer name with no catalogue row gets a stub row (Waxpeer's Steam-CDN image,
  Waxpeer's `type` as category) until the next import overwrites it.
- **Prices, every 5 min** (`skins_price_sync`): stream the CSV snapshot (237 MB of text, 1.19 M
  rows, **9.3 s** to stream and aggregate with our key, never buffered whole — the first probe
  that read it into memory was OOM-killed inside the api container), aggregate per canonical
  name, upsert only rows whose `price_hash` changed, bump the catalogue cache version, write
  facets. `/v1/prices` supplies `steam_price` and the stub metadata in the same tick (5.7 MB,
  0.8 s).
- **Neither job runs in the api process.** Both live in `apps/scheduler`; the module exposes
  the functions they call.

### 4.4 Taxonomy

Category slugs: `rifles`, `pistols`, `smgs`, `heavy`, `knives`, `gloves`, `agents`, `cases`,
`keys`, `music-kits`, `charms`, `stickers`, `graffiti`, `patches`, `collectibles`, `highlights`,
`other`. Skins take theirs from ByMykel `category.name`; every other file maps to one slug.
Exterior is an enum `FN | MW | FT | WW | BS`. v1 ships weapons, knives, gloves, agents, cases,
keys, music kits and charms; stickers, graffiti, patches, collectibles and highlights are
imported but hidden behind `cs2_skins_categories` until wanted.

### 4.5 Reads

Every catalogue read is Postgres/Redis; nothing on the listing, category, search or facet path
calls Waxpeer:

- `GET /skins/catalog` — filters (category, weapon, exterior, stattrak, souvenir, price
  range, `q`), sort (`price`, `-price`, `discount`, `popular`), keyset cursor; Redis 60 s per
  query, keyed with the catalogue version so a sync invalidates everything at once.
- `GET /skins/facets` — counts per category / weapon / exterior over active rows; Redis 60 s.
- `GET /skins/suggest?q=` — ten names by trigram similarity over `search_text` after alias
  expansion; Redis 60 s per query.
- `GET /skins/{slug}` — the row, the sell price, the cheapest-listing summary.
- `GET /skins/{slug}/listings` — the one read that can reach Waxpeer: search v2 with
  `delivery_details=1`, filtered to `auto`, Redis 90 s + a 1 h stale twin, a process-wide
  token bucket at 18/min and a breaker; when the bucket is empty it answers from
  `cheapest_auto` (price and id, no float). This is a §10 carve-out and is listed in
  AGENTS.md with the gifts reads.

Sell price = `ceil_to_cent(partner_price × (1 + margin_percent/100))`, never below
`price_floor_usd` (listings at $0.005 exist; card acquirers have minimum charges). UZS through
`fx` as every other price.

## 5. Purchase

- One service SKU `cs2-skin` (variable price, like `steam-gift`), mapped to supplier `waxpeer`
  with `sku_supplier_mapping.kind = 'skin'`. `fulfillment_data`: `listing_id`,
  `market_hash_name`, `phase`, `tradelink`, `expected_units`.
- **Checkout** re-prices server-side (`orders.service` calls `skins.checkout.price_skin_line`,
  the `gifts` precedent): `GET /v1/check-availability?item_id=` for the live price and
  `selling`; ±2 % tolerance against the client's quote; if the listing is gone, the cheapest
  `auto` listing of the same name at ≤ paid price + 3 % is substituted; otherwise 409 with the
  next offer.
- **Before payment** (advisory, off the money path): the trade link is parsed and matched to
  the signed-in Steam account when there is one; `POST /v1/check-tradelink`; Steam
  `GetTradeHoldDurations` — a non-zero escrow means the account has no mobile authenticator
  for 7 days and the trade would sit in a hold where either side can cancel. v1 refuses such
  links with the reason. This closes the "8-day cancellation" scenario at the door rather than
  detecting it after the money moved.

## 6. Fulfilment and tracking

1. Payment confirmed → task `pending`, order page shows the ready gate (§2.6).
2. Ready tap → `POST /v1/buy` with `project_id = task.id`, `price = expected_units`. Success →
   task `in_progress`, a `skin_trades` row (Waxpeer trade id, listing id, name, units paid,
   numeric status, `escrow_status`, `is_released`, `release_date`, `send_until`, Steam
   `trade_id`, seller fields, `penalties`, `last_checked_at`). Lost response → look up by
   `project_id` first; only a confirmed absence is a retry.
3. Status: a Socket.IO listener in `apps/worker` is the nudge, the minute-by-minute
   `waxpeer_reconcile` sweep (which already covers every `in_progress` `waxpeer` task) is the
   truth via `check-many-project-id`; both call `process_webhook_update`. Rules: **5 → delivered**
   (the only success); 4 with `is_released=false` → still in progress, order page says «Steam
   удерживает обмен до <release_date>»; 6 → failed, `MoneyOutcome.RETURNED` → the existing
   automatic customer refund, plus an ops alert with `reason`; `penalties` present →
   `MoneyOutcome.SPENT` for the penalty and a separate alert.
4. Customer UX on the order page: «Покупаем» → «<seller> отправил обмен — примите в Steam до
   HH:MM» with the deep link → «Получено» / «Steam удерживает до …» / «Отменено — деньги
   вернутся».
5. A daily `POST /v1/my-history` sweep over the last 14 days compares terminal statuses with
   ours and alerts on any divergence — a trade reverted after we called it delivered.

## 7. What we ask Waxpeer

- Partner status (the 20/min search limit is what stands between us and a smooth item page).
- Whether "Buyer failed to accept" is penalised as buyer fault, and whether a streak of failed
  purchases sets `no_p2p_until` on an API-buying account.
- Whether `auto`/`delivery` on search v2 are stable fields.
- The Socket.IO trade event's name and payload; whether a repeat `/v1/buy` with the same
  `project_id` is deduplicated; whether the item is in the buyer's inventory during
  `steam_hold`.

## 8. Spike (parallel, not in the repo)

One purchase of the cheapest `auto` listing (~$0.10) to a test Steam account with a 7-day-old
mobile authenticator, with a Socket.IO catch-all listener and a status poll logging everything:
time from buy to offer, the event name, `stage` values, `send_until` for a regular trade, hold
behaviour. Answers half of §7 without a support thread.

## 9. Delivery order

Four plans, each shippable behind `cs2_skins_enabled`:

1. **Catalogue backend** (`docs/superpowers/plans/2026-09-28-cs2-skins-catalog.md`): tables,
   parsers, the two sync jobs, the read API, settings. Testable without a purchase.
2. **Storefront pages** (web + miniapp): catalogue, category, item, search — read-only.
3. **Purchase**: checkout hook, pre-checks, the fulfiller branch, `skin_trades`, Socket.IO
   listener, order-page states, refunds and alerts. Starts after the spike.
4. **Admin and ops**: trades screen (holds, penalties, rollbacks), settings, runbook, the
   14-day history sweep, merchant API exposure.

## 10. Measurements (2026-09-28, live API, our key)

- CSV snapshot: 1 192 169 listings, 23 833 names; `auto` true on 1 114 276 (94 %); under $20:
  873 061 auto vs 36 842 manual; 21 989 names have an auto listing, 1 844 have none, and for
  1 822 names the cheapest listing is manual — the reason `/v1/prices` alone cannot price the
  catalogue.
- `/v1/prices?minified=0`: 23 893 names, 5.7 MB, 0.8 s; `type` distribution: Stickers 6565,
  Rifles 3919, Knives 3548, Pistols 3434, SMGs 2362, Heavy 1635, Graffities 852, Gloves 467,
  Music Kits 183, Weapon Charms 78, Agents 63, Case 44, Keys 14; 17 611 names under $50.
- Search v2 `AK-47 | Redline (Field-Tested)`: 50 listings, 49 `auto`, all `delivery: "p2p"`;
  `Glock-18 | Water Elemental (Field-Tested)`: 50/50 `auto`, `delivery: "bot"`.
- `/v2/get-items-list` returns `partner_price` (equal to `price` for our account today).
