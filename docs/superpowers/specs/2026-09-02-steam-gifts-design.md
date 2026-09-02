# Steam Gifts (G-Engine gifts-apps) — Design

**Status:** draft for review · **Date:** 2026-09-02 · **Owner:** catalog/fulfilment

## 1. What we are building

A «Steam Гифты» section of the storefront selling any of G-Engine's ~4 200
Steam games/DLC as a **gift delivered to the buyer's Steam account**: the
buyer picks a game, pastes their Steam friend-invite link, pays in UZS, and
G-Engine's bot gifts the game. Reference UX is G-Engine's own B2B panel:
hot-offers carousel (discounts), instant search, tags.

## 2. The shape of the upstream (verified live, 2026-09-02)

- `GET /gifts/apps` — paginated catalog, **4 241 items**, with server-side
  `search`, `filters`, `sort`. Item: Steam app id, name, `type` (game/dlc),
  Steam-CDN `image`, description, wholesale `price` (USD), discount fields
  (`discount_percent`, `discount_end_date` — moves with Steam sales),
  `packages`/`package_ids` («издания»), DLC links, `parent` for DLC.
- `GET /gifts/apps/{app_id}` — full card with `dlc[]` and `packages[]`.
- `POST /gifts/orders {invite_url, package_id, region}` →
  `GiftsOrderResponse` with `uuid`, `purchase_price`, `is_refunded` and
  status walk `accepted → prepared → delivering → shipped → delivered`
  (`canceled`/`refunded` terminal). Delivery is minutes-to-hours, not
  instant.
- No reservation step (unlike `/shop`): create IS the purchase intent.

## 3. Core decision: live catalog, not imported SKUs

4 241 positions with daily-moving prices are **not imported** as SKUs.
Instead:

- **Catalog is proxied live** through our API with a Redis cache, exactly
  like the storefront consumes our own catalog today.
- **Checkout is dynamic** on the Telegram-Stars pattern: one service SKU
  (`steam-gift`, `variable_amount`-like), and the order item's
  `fulfillment_data` snapshots `{app_id, package_id, app_name, region,
invite_url, supplier_price_usd}`. Our sell price is computed at
  order-creation from the live supplier price and frozen in the order — a
  Steam sale ending an hour later cannot corrupt a paid order.
- Phase 2 (explicitly out of scope now): top-selling titles get real
  SKU/product pages for SEO once the live section proves demand.

Precedent: `tg-stars-any` already sells a variable thing through one SKU;
sourcing already routes per-SKU to a supplier Fulfiller; the fulfilment
queue already polls suppliers with non-instant delivery (G2B game orders).

## 4. Backend

### 4.1 Client (`gengine_client.py` additions)

- `list_gift_apps(*, limit, offset, search=None, sort=None) -> (items, total)`
- `get_gift_app(app_id) -> dict`
- `create_gift_order(*, invite_url, package_id, region) -> GiftOrder`
- `get_gift_order(order_id) -> GiftOrder`
- `GiftOrder` dataclass: id, uuid, status, purchase_price, is_refunded, error.

### 4.2 Public catalog endpoints (`catalog` module or new `gifts` module)

- `GET /catalog/steam-gifts?search=&sort=&limit=&offset=` → items
  `{app_id, name, image, type, price_display (UZS, our margin applied),
price_usd, discount_percent, packages: [{id, name}]}`.
  - Redis cache: default listing pages and hot-offers **1 h TTL**; search
    queries cached 15 min keyed by normalized query. Upstream failure serves
    the stale cache (`stale-while-error`) and logs.
  - «Горячие предложения» = top-N by `discount_percent` plus a curated
    pinned list (admin-editable later; constant in v1).
- `GET /catalog/steam-gifts/{app_id}` → full card (DLC, packages) for the
  game page/modal.
- Prices shown = `supplier_price × (1 + margin) × fx(USD→UZS)`, margin from
  `STEAM_GIFTS_MARGIN_PERCENT` (default **10** — the gift market is
  price-transparent; 20% would price us above Steam UZ. Operator-tunable).

### 4.3 Checkout

- Service SKU `steam-gift` under new brand «Steam Гифты» (brand page is the
  custom section, § 5). SKU flagged so ordinary grids skip it (same
  mechanism that keeps `tg-stars-any` special-cased).
- `POST /orders` path extends its Stars-style branch: order item carries
  `fulfillment_data` as in § 3; server RE-FETCHES the app price at order
  creation (never trusts the client's number), applies margin+fx, and
  refuses if the app vanished or price moved > ±2 % from what the client
  displayed (client then re-renders).
- `invite_url` validated by shape
  (`https://s.team/p/…` or `steamcommunity.com/user/…` invite forms).
- Risk: the `steam-gift` brand joins `risk_liquid_brands` (gift games are
  resellable); all existing holds apply.

### 4.4 Fulfilment (`gengine.py` fulfiller)

- New route in `fulfill()` for gift items: `create_gift_order` →
  poll `get_gift_order` via the existing queue retry/poll machinery until
  `delivered` (success) or `canceled`/`refunded`/`error` (failed with
  reason). Statuses map onto the delivery timeline the customer already
  sees; `shipped` publishes a realtime «почти готово» step (v1: keep
  fulfilling until delivered — no new customer-facing states).
- Idempotency: before creating, look up our task's recorded gift-order id
  (in task/attempt metadata) and resume polling instead of re-buying —
  same recover pattern as `_recover(uuid)` for recharge orders.
- Refunds: `is_refunded=true` or `canceled` → task failed with reason; the
  usual manual/auto refund paths take over.

### 4.5 Settings

`STEAM_GIFTS_ENABLED` (master flag, default false — deploy dark),
`STEAM_GIFTS_MARGIN_PERCENT` (10), `STEAM_GIFTS_REGION_DEFAULT` and
`STEAM_GIFTS_REGIONS` (CSV; **open question § 7**).

## 5. Storefront (web)

- Route `/store/steam-gifts` — the brand page for «Steam Гифты», custom
  layout instead of the SKU grid:
  - hero + «Горячие предложения» carousel (discount badges, Steam covers);
  - search box (debounced, hits our proxy endpoint → their server search);
  - results grid: cover, name, «Изданий: N», our UZS price, discount badge;
  - game modal/page: description, DLC list, package (издание) selector,
    region selector, `invite_url` input with a **guide** (screenshots: Steam
    → профиль → «Пригласить друга» → копировать ссылку) — the #1 support
    risk, the guide is part of v1, all three locales;
  - checkout continues through the normal cart/payment flow.
- Checkout timeline copy: «подарок отправляется ботом, обычно до часа» —
  expectations set at purchase, not in support chats.
- Mini App: **out of scope v1** (web first; the section is heavy).
- SEO: the section page itself is indexable with ItemList JSON-LD of the
  hot offers only (live prices for 4k items would churn the crawl); the
  sitemap lists just `/store/steam-gifts`.

## 6. Merchant feed / watchdog interplay

- The `steam-gift` service SKU is variable ⇒ **excluded** from the Merchant
  Center feed and per-SKU JSON-LD automatically (existing rules).
- Catalog watchdog does not apply (no static mappings). The section's own
  failure mode is upstream-down ⇒ stale cache + a `gifts_catalog_stale`
  log/alert after N hours.

## 7. Open questions (blocking launch, not build)

1. **`region` values** — the API types it as free string; ask the G-Engine
   manager for the accepted enum and semantics (recipient's Steam account
   region?). Build ships with a settings-driven list; launch needs the real
   values. Wrong region = failed/refunded gift, so v1 UI defaults to one
   region until confirmed.
2. **Margin final value** — default 10 %, operator decision; compare
   against Steam UZ shelf prices for the top-20 titles before launch.
3. Do gift orders need G-Engine balance top-ups sized differently? (Their
   AAA titles are $30–40 wholesale — balance alerting thresholds may need a
   raise; existing low-balance alert covers it, verify the threshold.)

## 8. Testing

- Client: respx contract tests for the four endpoints + status walk.
- Catalog proxy: cache hit/miss/stale-on-error; search pass-through; price
  math (margin+fx) pinned.
- Checkout: price re-fetch and ±2 % refusal; invite_url validation; risk
  hold applies (liquid brand).
- Fulfiller: create→poll→delivered; resume-not-rebuy on retry; canceled ⇒
  failed task; refunded flag honored.
- Web: search flow, package selector, guide rendering (vitest); e2e happy
  path behind the flag.

## 9. Rollout

1. Deploy dark (`STEAM_GIFTS_ENABLED=false` everywhere).
2. Enable on prod for internal testing; buy one cheap game ($1–3) to our
   own Steam account end-to-end.
3. Confirm region enum with G-Engine; then public: flag on, announce.
