# CS2 Skins — Purchase UI (plan 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A signed-in customer buys a CS2 skin from the web item page (`/skins/{slug}`) and the
mini app (`/cs2-market/{slug}`): picks an offer, gives a trade link, pays like any order, and
follows the Steam offer on the order page until «Получено» — or sees the money back on the
balance.

**Architecture:** No new purchase API — plan 3a's order pipeline is used as is
(`POST /orders` with the `cs2-skin` SKU + `POST /payments/intents`, the order's
`items[].skin_trade`). One small API addition: `/skins/{slug}` returns `buy_sku_id` so the
pages know which SKU to order. Web: `lib/skin-checkout.ts` (the `gift-checkout` shape,
signed-in only) + a client `SkinBuyPanel` + a `SkinTradeCard` on the order page. Mini app: the
same through `performCheckout` + `SkinTradeCard` in `ItemCard`. Payment methods and the wallet
tile reuse each app's existing libraries (`payment-providers`, `wallet-balance`,
`PaymentMethodGrid`, `WalletPayOption`).

**Spec:** `docs/superpowers/specs/2026-09-28-cs2-skins-design.md` (§2, §5, §6.4, §8.1); backend
plan `docs/superpowers/plans/2026-09-28-cs2-skins-purchase-backend.md`.

## Global Constraints

- Sign-in required (guests: web opens the login modal; the mini app is always signed in).
- One skin per order; any offer can be bought; price from the offer, re-checked by the API.
- Copy: short, outcome-first, no service meta, nothing Waxpeer-branded; the seller's name and
  avatar are shown on the order page on purpose (spec §2.3). ru/en/uz in the same commit.
- Money in minor-unit strings; `Intl` formatting (existing `displayPrice` / `skinPriceText`).
- Nothing cached: orders are read with `no-store` (plan 3a Task 0).
- Web route JS ≤ 180 KB, mini app pages stay lazy chunks.

## Review Focus

1. A guest on web taps «Купить» → sign-in, then lands back on the same skin with the offer chosen.
2. A price that moved (422 `expected_amount_usd`) or a sold listing (422 `listing_gone` +
   `next_offer`) never charges silently: the panel shows the new price / next offer to confirm.
3. The order page never promises a refund for `reason_code: support`.
4. «Открыть обмен» opens `offer_url` in Steam (mini app: `openExternalLink`, not in-app nav).
5. A trade link that fails the check blocks «Оплатить» except on `unavailable`.

---

### Task 0: API — `buy_sku_id`, and the regenerated types

- `SkinDetailOut.buy_sku_id: str | None` — the active `cs2-skin` SKU's id (cached per process,
  `None` until the seed ran). Integration test: present after seeding, `None` before.
- `make gen-api` (the `support` reason code from plan 3a's M3 lands in the generated types).
- Commit `feat(api/skins): item detail names the SKU to order`.

### Task 1: Web — checkout lib

**Files:** Create `apps/web/src/lib/skin-checkout.ts` + test; modify `lib/orders-types.ts`
(`skin_trade`), `lib/skins.ts` (`SkinDetail.buy_sku_id`, `getTradeLink`, `saveTradeLink`,
`checkTradeLink`).

- `buySkin({skuId, slug, listingId, tradelink, amountUsd, provider, locale, orderKey})` →
  `{orderId, intentUrl, trackHref}`; Bearer only (a missing token throws `SignInRequiredError`).
- Errors: `SkinPriceChangedError(expectedUsd)`, `SkinListingGoneError(nextOffer | null)`,
  `SkinTradeLinkError(reason)` (`tradelink_other_account`, `invalid`), plus the gifts one-retry on
  "order not awaiting payment".
- Tests (node, fetch stubbed): happy path body/headers; each 422 → its error; guest → sign-in error.

### Task 2: Web — buy panel on the item page

**Files:** Create `components/skins/SkinBuyPanel.tsx` (+ test), `SkinTradeLinkField.tsx`
(+ test); modify `SkinPriceBlock.tsx` (the disabled button goes), `SkinListings.tsx` (a «Купить»
per row selects that offer), `[slug]/page.tsx`, i18n `web.skins.buy.*`.

- Selected offer: the cheapest by default; a row's «Купить» selects it and scrolls to the panel.
- Trade link field: prefilled from `GET /skins/tradelink`; «Где найти?» links to Steam's
  trade-offer privacy page; checked on blur / paste (`POST /skins/tradelink/check`), verdict line
  per reason; `unavailable` shows nothing blocking.
- Payment: the gifts methods (payme/click/uzum from `payment-providers`) + the wallet tile
  (`wallet-balance`), same availability rules; confirm modal (`ConfirmPurchaseModal`).
- Guest: «Купить» opens the login modal and remembers `?offer=<id>` in the URL.
- Errors → inline: price changed (new price + «Купить за N»), listing gone (next offer + «Купить
  его за N»), trade link (the reason line).
- Tests (jsdom): guest → login modal; prefilled link; `private` verdict blocks pay; price-changed
  shows the new price; listing-gone swaps to the next offer.

### Task 3: Web — trade card on the order page

**Files:** Create `components/order/SkinTradeCard.tsx` (+ test); modify `OrderStatus.tsx`
(render it for items with `skin_trade`, next to `OrderItems`; faster poll while `buying` /
`offer_sent`), i18n `web.skins.trade.*`.

- `buying` — «Покупаем скин — обмен придёт в Steam через минуту».
- `offer_sent` — seller avatar + name, «Открыть обмен в Steam» (`offer_url`, new tab), accept-by
  countdown from `send_until`.
- `accepted` — «Получено», «Steam защищает обмен до <date>».
- `released` — «Получено».
- `failed` — `not_accepted`/`sold_out`: «Деньги вернулись на баланс» + wallet link;
  `support`/`other`: «Мы проверяем покупку — напишите в поддержку» + support link.
- Tests: each state's copy and link; `support` never says "вернулись".

### Task 4: Web — brand routing

- `BrandTile` maps `cs2-skins` → `/skins`; `store/[brandSlug]/page.tsx` redirects `cs2-skins` to
  `/skins` (no static directory — `route-shadowing.test.ts`). Test for both.

### Task 5: Mini app — buy flow

**Files:** modify `apps/miniapp/src/lib/skins.ts` (`buy_sku_id`, trade-link get/save/check),
`src/lib/orders.ts` (`OrderItemOut.skin_trade`), `pages/CS2Skin.tsx`; create
`components/skins/SkinBuyPanel.tsx`, `lib/skin-buy.ts` (+ test: error mapping, key fingerprint).

- Same rules as web: offer selection (row tap), trade link field with «Где найти?», method grid
  (`PaymentMethodGrid`) + wallet (`WalletPayOption`), `performCheckout` with a sticky order key,
  `openExternalLink(intent_url)` for acquirers, then `/order/{id}`.
- Errors as web (price changed, listing gone, trade link).

### Task 6: Mini app — trade card + routing

- `components/order/SkinTradeCard.tsx`; `ItemCard` branches on `item.skin_trade` before the
  delivery check; «Открыть обмен» → `openExternalLink(offer_url)`.
- `lib/routes.ts`: `cs2-skins` → `/cs2-market`; `HomePromoCards` drops the «Скоро» badge.
- A pure `skinTradeView(trade)` helper (copy keys, CTA, countdown) with node tests.

### Task 7: Docs + checks

- `docs/product/flows/skins-buy.md` (UI states), module README, runbook launch steps (the
  storefront buttons are live once the seed is applied and `CS2_SKINS_ENABLED` is on).
- web + mini app suites, tsc, eslint, `prettier --check .`; screenshots at 1440 / 390 / 360.
