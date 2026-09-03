# Runbook — Steam Gifts

Steam gift games/DLC, sold live through G-Engine's `/gifts/*` endpoints and
delivered to the buyer's own Steam account. See
[ADR-0066](../decisions/0066-steam-gifts-live-catalog.md) for the design
and `docs/product/flows/steam-gifts.md` for the buyer-facing flow. The
module is `apps/api/src/yupay/modules/gifts/`
(`apps/api/src/yupay/modules/gifts/README.md` for the internal API); the
fulfilment branch is
`apps/api/src/yupay/modules/fulfillment/suppliers/gengine_gifts.py`.

> Customer-facing name (2026-09-03): **«Steam Игры»** — display only. The
> slug, routes, and `STEAM_GIFT_SKU_CODE` all stay `steam-gifts`.

## The flag

- **Env var**: `STEAM_GIFTS_ENABLED`. Default `false` everywhere — the
  feature ships dark. Home: wherever the api container's env lives per
  environment (`secrets/api.env` on prod, same pattern as `FULFILMENT_ASYNC`
  — see `docs/runbooks/fulfillment-queue.md`).
- **Flipping it needs an api restart only.** `Settings` is read once at
  process start, and every `gifts.routes` route is guarded by a single
  router-level dependency (`_ensure_enabled`) that 404s the whole `/gifts/*`
  surface while the flag is off — so a route added later inherits the guard
  automatically and there is nothing else to toggle per-route.
- **The web section needs no deploy of its own.** `/store/steam-gifts` and
  the game page call the same `/gifts/catalog*` endpoints; once the api
  answers instead of 404ing, the already-deployed frontend section un-404s
  on its own. There is nothing to flip on web/miniapp.
- **Checkout is gated the same way**, independently:
  `gifts.checkout.price_gift_line` also checks
  `settings.steam_gifts_enabled` and refuses (422) if it's off, so a stale
  cached page cannot slip a purchase through while the flag is off even
  for a moment during the restart.
- Order: flip the flag, restart api, confirm `GET /api/v1/gifts/catalog/hot`
  returns 200 (not 404), then check the storefront section renders.
  Reverting is the same restart in the other direction — nothing to
  migrate or roll back, since the flag guards reads and writes alike.

## Regions

**Two units, deliberately different (2026-09-03 "region v2").** The
**zone** (`CIS`/`RU`/`KZ`/`UA`) is G-Engine's pricing bucket — it's what
`STEAM_GIFTS_REGIONS`/`gifts.settings.offered_zones` sells against, and it
stays the wire unit. The **country** (`UZ`, `GE`, `KG`, …) is the
buyer-facing unit: what the country picker offers and what
`fulfillment_data.region` carries from the client. `gifts/service.py`'s
`ZONE_COUNTRIES` is the curated map from a zone to the countries it
covers — offered zones only, e.g. `CIS` → `(UZ, GE, KG, MD, TJ, TM, AM,
AZ, BY)` with `UZ` first (our home market). `zone_for_country` resolves a
chosen country back to the zone to price from; `countries_for_zone`
expands a zone into its countries for the picker (`routes.py::_regions_out`
assembles `GiftAppDetailOut.regions` this way). A zone absent from the map
falls back to its own representative country — the `region` field on that
zone's priced entry — so widening `STEAM_GIFTS_REGIONS` to a
not-yet-curated zone still sells (as a single-country zone); update
`ZONE_COUNTRIES` separately to group it into real countries.

`STEAM_GIFTS_REGION_DEFAULT` (default `UZ` as of 2026-09-03 — a country
code now, was the zone label `CIS` before the country picker; prod's
`secrets/api.env` carries no override, so this code default is what ships)
and `STEAM_GIFTS_REGIONS` (CSV of _zones_, default `CIS,RU,KZ,UA`) are read
fresh from settings on every request
(`gifts.settings.offered_zones`/`default_zone`) — changing either only
needs an api restart, no migration. Per spec §7.1, **CIS** (the zone `UZ`
buckets into) is the confirmed recommendation for Uzbekistan (the
operator's own test purchase delivered successfully with it); do not widen
`STEAM_GIFTS_REGIONS` without checking the new zone actually prices
packages G-Engine sells (an offered zone with no price on a given package
is silently dropped from that game's `zones`/`regions` lists — see
`routes.py::get_catalog_app`).

**Backwards compatibility.** `gifts/checkout.py::price_gift_line` still
accepts a legacy zone label (`CIS`, `RU`, `KZ`, `UA`) in
`fulfillment_data.region` — an order placed before this shipped, or a
client that hasn't reloaded, keeps pricing exactly as it did before.
Resolution order: try `region` as a country via `zone_for_country`; if
that's `None`, accept it as-is only when it's one of the offered zones;
otherwise 422 ("this region has no price for the selected edition"). The
resolved zone is stored separately as `fulfillment_data.zone`, so a
support ticket can always tell which pricing bucket an order actually
used regardless of what unit the buyer (or a stale client) submitted.

**The zone is only ever our pricing/wire unit — no customer-facing label
of either kind reaches G-Engine.** `POST /gifts/orders`'s `region` field
wants the 2-letter country code carried on the _chosen package's own_
`prices[]` entry (`PackagePriceResponse.region`, lowercase — e.g. `"kz"`,
`"ua"`, and for zone **CIS** it can be e.g. `"ge"` — verified live, and it
can differ per package). Sending the zone label (`"CIS"`, `"KZ"`, …) _or_
the buyer's country code (`"UZ"`) gets G-Engine's «Price not found».
`gifts/checkout.py::price_gift_line` resolves the code at checkout time —
from the exact same priced entry `supplier_price_usd` is billed from, via
`gifts/service.py`'s `zone_region_code` (sharing the one price-entry
finder with `zone_price_usd`, so the two come from the same entry; a
malformed entry without a region code is refused at checkout) — and
stores it on the order line as `fulfillment_data.region_code`.
`gengine_gifts.py::fulfill_gift` sends `region_code` when present, falling
back to the legacy `region` value only for order rows written before this
resolution existed (2026-09-03 hotfix — no backfill needed, the feature
had never gone live and zero pre-hotfix gift orders exist on prod).

**"Api restart only" depends on the product's `region` field staying a
plain `text` field with no options.** The seed
(`scripts/seed/2026-09-03_steam_gifts.py`) deliberately declares `region`
as `type: "text"`, not `type: "select"` with a literal option list — a
`select` field is checked for option membership by
`orders/validation.py::validate_fulfillment_data`, which runs **before**
`gifts/checkout.py::price_gift_line`'s `zone_for_country`/`offered_zones`
resolution ever sees the value, so a `select`-typed schema would be a
second, DB-stored source of truth for which regions are legal and widening
the env var alone would still 422 the new zone. `zone_for_country`/
`offered_zones()` are the only membership checks that matter —
verify that's still true (`region` is `text` on the live `products` row,
no `options` key) before trusting "just restart the api" for a region
change; if a prior seed run left the field as `select`, re-run the seed
with `--apply` to correct it (the seed's idempotent path now syncs
`required_fields` on an existing row instead of skipping it).

## "gifts catalog stale" — what the log means

`gifts.catalog_stale` (a `log.warning` in `gifts/service.py::_cached_json`)
fires whenever a fresh Redis key expired or missed **and** the live
G-Engine call failed (`GEngineError`/`GEngineUnavailableError`) — the
response the browser got was the up-to-24h-old stale twin
(`gifts:*:stale`), not a live read. One or two of these during a G-Engine
blip is normal and self-heals on the next successful fetch (which
refreshes both the fresh and the stale key together). A sustained run of
these — the storefront visibly showing prices/discounts that don't move —
means G-Engine has been down long enough to matter; check
`/admin/integrations/gengine/health` (the same health probe the shop/
recharge lines use) for connectivity and wallet balance. During a
sustained `gifts.catalog_stale` run, prefer flipping `STEAM_GIFTS_ENABLED`
to `false` over continuing to sell at prices that may be up to a day old —
see [The flag](#the-flag) above for what that does and doesn't affect.

**If the stale key is also gone** (nothing was ever successfully cached,
or the 24h stale TTL lapsed during a long outage), the request instead
gets an `UpstreamUnavailableError` → **502** — a customer sees a real
error on that page, not silently stale prices. This is the intended
fail-mode: never invent a price to show, never serve data with an
unbounded age.

Checkout during a G-Engine outage fails the same way: `price_gift_line`
calls the same 15-min-cached `get_app`, so it can serve a warm stale
cache for pricing, but a cold one propagates the 502 to the order-create
call — an honest failure the client can retry, not a purchase at a
guessed price.

## Parked gift tasks — `gift order not found at supplier`

A fulfilment task with `last_error = "gift order not found at supplier
after create timeout — manual review"` means: the original
`POST /gifts/orders` call got an ambiguous failure (timeout/5xx — we never
saw G-Engine's response), the task waited `GIFT_ADOPT_WINDOW_MINUTES`
(30) for a matching order to become findable via the adopt probe, and
none ever did. **This does not mean no money moved** — it means we
genuinely don't know, and the task needs a human to look.

The task carries everything needed to look it up in `extra_metadata`:
`gift_search` (the invite-url tail G-Engine's search accepts, ≤36 chars —
`GIFT_SEARCH_MAX`), `gift_invite_url` (the full canonical link), and
`gift_package_id`. The order's own `created_at` is the lower bound the
automatic probe used.

1. **Open G-Engine's own merchant panel** and search gift orders for
   that Steam profile/invite link and package, placed around the order's
   `created_at`.
2. **Nothing found** — the create genuinely never landed. Hit **Retry**
   (`POST /admin/fulfillment/tasks/{id}/retry` or the admin UI button).
   `fulfill_gift` re-runs the exact same probe first and, finding
   nothing, creates a fresh order — safe, this is the intended path for
   a create that truly never happened.
3. **An order is found** (status `shipped`/`delivered`, i.e. it actually
   went through even though our probe never matched it — a search
   quirk, a probe outside the matched window, whatever the cause) —
   **do not hit plain Retry.** `fulfill_gift`'s own adopt probe uses the
   same search G-Engine's panel does; if a human found it and Retry's
   automatic probe didn't, blindly retrying risks a second purchase.
   Instead, **force-complete** the task by hand with what the panel
   shows: `POST /admin/fulfillment/tasks/{id}/force-complete` with
   `artifact_kind: "topup_receipt"` and an artifact carrying at least
   `{"app_name": ..., "package_name": ..., "message": "Steam прислал вам
подарок — примите его…"}` (mirror `_DELIVERY_MESSAGE` in
   `gengine_gifts.py`) — put the G-Engine order id you found in
   `admin_note` for the audit trail. This walks the order to `delivered`
   without ever calling the fulfiller again.
4. **An order is found but still `delivering`/`accepted`/`prepared`** —
   don't force-complete yet (that would tell the customer it's done
   before it is) and don't retry (risk of a duplicate). Wait and
   re-check the panel; a `failed` task is **not** swept by the 60s
   `gengine_reconcile` job (it only sweeps `in_progress` tasks), so it
   will not resolve itself — you have to come back to it once G-Engine's
   own status moves.
5. **Refund instead** — if the game is no longer sellable, the customer
   wants out, or you've confirmed via the panel that the create never
   happened and a re-buy isn't wanted, refund through
   `POST /admin/payments/{payment_id}/refund` (see
   `docs/runbooks/wallet-refunds.md` for the wallet-vs-external-provider
   ledger detail) rather than retrying. `fail_manual_task` does **not**
   apply here — it's restricted to `supplier == "manual"` tasks; a
   parked gengine task is failed by the adopt-window timeout itself, not
   by that endpoint.

**Known accepted limitation.** `/gifts/orders` takes no client-chosen
idempotency token, so the adopt probe matches purely on `invite_url` +
`package_id` within a time window. Two near-simultaneous, otherwise
identical gift purchases for the same recipient and package can, in rare
cases, have the wrong task adopt the other's order under queue lag — the
practical failure mode is "task A's delivery card shows task B's game
receipt," not lost money or a double charge (both purchases still exist
and were still paid for). This is accepted, not a bug to chase: G-Engine's
API gives no stronger key to disambiguate on. If a customer reports a
mismatched-looking gift receipt for a purchase placed within seconds of
another identical one, reconcile the two tasks by hand against G-Engine's
panel (see [ADR-0066](../decisions/0066-steam-gifts-live-catalog.md)'s
negative consequences).

## Post-`shipped` `refunded` — recipient declined the gift

`shipped` is **our** success (the task is `succeeded`, the order is
`delivered`, `check_status` never runs on it again). Steam's own
`delivered` only fires once the recipient accepts, which can take days —
and the recipient can also **decline**, which G-Engine reports as
`refunded` sometime after we already counted the sale as done. Nothing in
the fulfilment state machine watches for this on purpose (spec §4.4): a
succeeded task is not re-polled.

If a customer reports "I never got my gift" on an order that shows
`delivered`:

1. Check `/orders/{id}/deliveries` — confirm the delivery artifact's
   `external_order_id` (admin-only field, not customer-visible).
2. Look that order up in G-Engine's panel. If its status is `refunded`,
   the recipient declined (or the gift was reversed for some other
   reason on Steam's side) after we already marked it delivered.
3. This is a **manual refund**, same mechanism as any other post-delivery
   refund: `POST /admin/payments/{payment_id}/refund` — see
   `docs/runbooks/wallet-refunds.md`. There is no automatic path; the
   fulfilment task itself stays `succeeded` (it was correct at the time),
   and no code change is expected here — this is the existing
   stuck/refund manual process, reused, not a Steam-gifts-specific one.

## Changing the margin

`gifts:margin` in Redis (1h TTL) sits in front of `steam_gift_settings`
row 1 in Postgres. Two ways to change it:

- **Admin page** (`/gifts` in the admin SPA) → `PATCH
/admin/gifts/settings {margin_percent}`. This writes Postgres, commits,
  and only then publishes straight into Redis (`publish_margin`) — the
  change is live **immediately**, not after the TTL. Every api process
  picks it up on its next read because they all share the same Redis key,
  not a per-process cache.
- **Direct DB edit** (emergency only, bypasses the admin audit trail) —
  update `steam_gift_settings` row 1 and either wait out the 1h TTL for
  Redis to fall through to Postgres again, or flush the key by hand:
  `redis-cli DEL gifts:margin` forces the next read to hit Postgres
  immediately. Prefer the admin page; this path leaves no `updated_by`
  audit trail.

`STEAM_GIFTS_MARGIN_PERCENT` (env, default `10`) only seeds row 1 on the
very first read if the row doesn't exist yet — changing the env var after
that has **no effect**. Don't expect an env change to move a live margin;
use the admin page.

## Ops checklist for launch

Beyond flipping `STEAM_GIFTS_ENABLED` (above), these are separate,
one-time operator actions before announcing the section publicly (spec
§9, step 3):

- [ ] **Add `steam-gifts` to `RISK_LIQUID_BRANDS` on prod.** The env
      default (`risk_liquid_brands` in `core/config.py`) is
      `roblox,telegram-stars,steam` and does **not** include
      `steam-gifts` — the brand slug this feature seeds
      (`scripts/seed/2026-09-03_steam_gifts.py`'s `BRAND_SLUG`). Gift
      games are resellable (spec §4.3), so this brand needs the same
      antifraud identity-window scrutiny (ADR-0062) as Roblox/Stars/Steam
      wallet top-ups. This is a prod env var edit + api restart, not a
      code change — nothing in this feature's code adds it automatically.
- [ ] **Verify the G-Engine balance alert actually covers this brand.**
      As shipped, `supplier_low_balance_threshold` (default $50) only
      drives the **pre-emptive** low-balance warning
      (`integrations.price_refresh._maybe_warn_low_balance`) for **G2B**
      specifically (it checks `isinstance(fulfiller, G2bFulfiller)`) —
      **G-Engine is not covered by that alert at all.** The **per-order**
      low-balance alert (`fulfillment.service._maybe_alert_low_balance`)
      fires generically off `result.error == "supplier_low_balance"`, but
      `gengine_gifts.py` never sets that error string — a G-Engine
      create failing on insufficient wallet funds surfaces today as a
      plain `GEngineError` → a normal `failed` task with no low-balance
      alert and no auto-hide from the customer (unlike the low-balance
      hide `fulfillment.service` gives G2B). AAA titles wholesale at
      $30–40 (spec §7.3), so a G-Engine wallet that drifts below that
      with no automated warning can fail several gift orders visibly
      before anyone notices. **Until this gap is closed in code**, check
      `/admin/integrations/gengine/health`'s `balance` field by hand on a
      cadence (daily, or before any marketing push) — do not assume the
      existing low-balance alerting protects this brand. Closing the gap
      properly (a G-Engine balance check either reusing
      `supplier_low_balance_threshold` or a G-Engine-specific one, and/or
      teaching `gengine_gifts.py` to detect a low-balance G-Engine
      refusal and set `_LOW_BALANCE_ERROR`) is a follow-up, not done by
      this task.
- [ ] **Confirm the prod G-Engine key's entitlement.** The **dev**
      G-Engine API key 401s on `GET /gifts/apps` — the gifts endpoints
      need an entitlement the dev key doesn't carry. The **prod** key was
      verified working live (2026-09-02). Before flipping the flag on in
      any environment other than prod (a staging smoke test, a second
      prod-like environment), confirm its G-Engine key has the gifts
      entitlement — otherwise every catalog read 502s
      (`UpstreamUnavailableError`) with no stale cache to fall back on
      yet.
- [ ] **One end-to-end test purchase** (spec §9 step 2) — buy one cheap
      game ($1–3) to an internal Steam account through the real flow
      before announcing, confirming the delivery card and the accept
      step both work as expected.

## Related

- [ADR-0066](../decisions/0066-steam-gifts-live-catalog.md) — design record
- `docs/product/flows/steam-gifts.md` — the buyer-facing flow
- `docs/architecture/module-map.md` — the `gifts` module and its edges
- `docs/architecture/cache-keys.md` — every `gifts:*` Redis key, TTLs, who
  writes them
- `docs/runbooks/fulfillment-queue.md` — the queue every gift task rides
  (`gengine_reconcile`'s 60s sweep only ever touches `in_progress` tasks)
- `docs/runbooks/wallet-refunds.md` — the refund mechanism referenced above
- `docs/runbooks/supplier-api-down.md` — if G-Engine itself is down, not
  just the gifts endpoints specifically
