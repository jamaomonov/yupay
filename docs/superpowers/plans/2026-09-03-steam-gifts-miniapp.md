# Steam Gifts Miniapp + Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Addendum to `docs/superpowers/plans/2026-09-03-steam-gifts.md` — same branch `feat/steam-gifts`.

**Goal:** A native Steam-gifts flow in the Telegram Mini App (catalog → game → checkout → «примите подарок» card), the generic top-up leak closed, and the customer-facing name changed to «Steam Игры».

**Architecture:** New wouter routes `/gifts` and `/gifts/:appId` (both React.lazy — first split in the app, deliberate: miniapp is over its 120KB budget), fed by the same public `/api/v1/gifts/*` endpoints web uses; checkout through the existing `performCheckout`; the `steam-gifts` brand tile and deep links re-routed away from `/topup/:gameId`.

**Tech Stack:** Vite 6 + React 19 SPA, wouter, TanStack Query v5, Tailwind v4 + local shadcn-style ui/ primitives, framer-motion, custom flat-key i18n (`packages/i18n/locales/*/miniapp.json`), Vitest 2 in node env (NO jsdom/RTL — test exported pure logic only).

**Spec:** `docs/superpowers/specs/2026-09-02-steam-gifts-design.md` (§5 layout intent) + the approved chat design (2026-09-03): hide generic flow, native catalog/game screens, lazy loading, rename display-only («Steam Игры»), slug unchanged.

## Global Constraints

- Backend contracts are FROZEN — no api changes in this plan. DTOs: `GET /api/v1/gifts/catalog[?search=&limit=&offset=]` → `{items:[{app_id,name,image,type,price_usd,price_uzs,discount_percent,packages_count,dlc_count}],total}`; `/hot` same; `/{app_id}` adds `description, packages:[{id,name,image,discount_percent,prices:[{zone,price_usd,price_uzs}]}], dlc_total, zones, zone_default`; all routes 404 when the flag is off — every fetcher tolerates it without throwing.
- Checkout body (proven by web + integration tests): `items:[{sku_id, qty:1, amount_usd:<selected price_usd string>, fulfillment_data:{app_id:int, package_id:int, region, invite_url}}]`; 422 price-drift carries `body.extra.expected_amount_usd`. Match errors by structure, never by message strings.
- Invite validation shapes (mirror `apps/web/src/components/gifts/GiftPurchasePanel.tsx` regexes exactly): `profiles/\d{17}`, `/id/[A-Za-z0-9_-]{2,32}`, `s.team/p/[A-Za-z0-9/_-]{1,64}`, scheme optional, https only when given, host compared exactly.
- Money stays strings; `Number()` only for display formatting.
- i18n: flat dotted keys in ALL THREE `packages/i18n/locales/{ru,en,uz}/miniapp.json` (ru is the canonical type source; parity test exists). No hardcoded user-facing strings.
- TS strict, no `any`, no uncommented `as`. Tests = exported pure functions only (node env).
- Never `next build` on host; do not restart docker; dev stack is already up with the flag on (api on :8000, miniapp dev on :3001).
- Conventional Commits; do NOT push; never stage the pre-existing dirty files (Makefile, scripts/seed.py, scripts/seed/2026-08-21_telegram_stars_unit_sku.py).

---

### Task M1: Miniapp gifts catalog + game screens, generic flow closed

**Files:**

- Create: `apps/miniapp/src/lib/gifts.ts` (+ `gifts.test.ts`), `apps/miniapp/src/pages/GiftsCatalog.tsx`, `apps/miniapp/src/pages/GiftGame.tsx` (+ colocated `.test.tsx` for exported logic)
- Modify: `apps/miniapp/src/App.tsx` (routes `/gifts`, `/gifts/:appId` via `React.lazy` + `Suspense` fallback using the existing skeleton conventions), `apps/miniapp/src/pages/Home.tsx` (tile + search-row for brand slug `steam-gifts` link to `/gifts` instead of `/topup/steam-gifts`), `apps/miniapp/src/pages/TopUp.tsx` (top-of-page guard: `gameId === "steam-gifts"` → `setLocation("/gifts")` redirect so deep links never see the raw form)
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (keys `gifts.*`)

**Interfaces:**

- Consumes: `apiGet` from `lib/api.ts` (anonymous:true for catalog), `SafeImage`/`Skeleton`/`Sheet`/`button`/`card`/`input` from `components/ui/`, `useT()` i18n, wouter `Link`/`useLocation`, web DTO shapes above; UZS formatting — find and reuse the miniapp's existing sum formatter (grep how TopUp prints prices).
- Produces (M2 consumes): `GiftGame` screen with state `{detail, selectedPackageId, selectedZone, inviteUrl}` and exported pure helpers `validateInviteUrl(value): string | null` (canonical or null) and `priceFor(detail, packageId, zone): {price_usd, price_uzs} | null`; lib functions `fetchGiftsPage(offset, search?)`, `fetchGiftsHot()`, `fetchGiftDetail(appId)`, `fetchGiftDlc(appId, q, offset)` — all safe on 404 (return empty/null).

Screens: **GiftsCatalog** — hot strip (horizontal scroll, discount badges) when non-empty, debounced (400 ms) search input, grid of cards (SafeImage cover, name, «Изданий · DLC» via plural keys, UZS price, discount badge), «Показать ещё» accumulate-append with query-reset (mirror web semantics incl. the race guard), skeletons + error-with-retry + empty states; if the very first page comes back empty (flag off) show `gifts.comingSoon`. **GiftGame** — cover/description, edition selector (buttons/sheet), zone selector (zones from detail, default `zone_default`, beyond 4 behind «другой регион»), zone without price disabled with hint, invite input with inline validation + «Где найти ссылку?» Sheet guide, price re-renders per selection, DLC collapsed: «DLC: N — показать» opens a Sheet with its own search + paged list (24) linking to `/gifts/:dlcAppId`. Buy button present but wired in M2 (disabled stub acceptable ONLY if M1+M2 land in separate commits the same session; prefer leaving the handler a no-op with TODO-free comment "wired in the checkout commit").

Steps: tests for exported logic first (`validateInviteUrl` accept/reject table copied from web's cases; `priceFor` selection; debounce/accumulate as pure reducer if extracted), fail → implement → pass; `pnpm --filter @yupay/miniapp test -- --run`, `tsc --noEmit` (or the package's typecheck script), lint; visual smoke on the running dev miniapp (:3001). Commit `feat(miniapp): steam gifts catalog and game screens, generic top-up closed`.

### Task M2: Miniapp checkout + «примите подарок» card

**Files:**

- Modify: `apps/miniapp/src/pages/GiftGame.tsx` (buy flow), `apps/miniapp/src/lib/gifts.ts` (SKU resolution + price-drift error extraction), `apps/miniapp/src/pages/OrderSuccess.tsx` (+ its `.test.tsx`), `apps/miniapp/src/pages/TopUp.tsx` ONLY if the provider-picker is extracted (prefer reusing without refactor), `packages/i18n/locales/{ru,en,uz}/miniapp.json` (`gifts.checkout.*`, `success.gift.*`)

**Interfaces:**

- Consumes: `performCheckout`/`useCheckout` from `lib/orders.ts` (`{skuId, fulfillmentData, amountUsd, qty:1, provider}`), `openExternalLink` from `lib/telegram.ts`, provider selection exactly the way `TopUp.tsx` does it (read its provider UI/state and mirror; do not import the whole page), `useGame("steam-gifts")`/catalog lib for resolving the single `steam-gift` SKU id (tolerate absence → render `gifts.comingSoon`), `ensureBotCanWrite` + closing-confirmation pattern from TopUp's submit (`TopUp.tsx:834-919`).
- Produces: exported `extractExpectedAmount(body): string | null` (reads `body.extra.expected_amount_usd`) and `isGiftDelivery(delivery): boolean` (artifact?.kind === "gift") — both unit-tested.

Behaviour: buy → checkout with the frozen body; success → `openExternalLink(intent_url)` (non-mock) + navigate `/order/{id}`; 422 with `expected_amount_usd` → invalidate/refetch detail + toast `gifts.checkout.priceChanged`; other errors → existing `checkoutErrorMessage` path (extend it if a gifts-specific message is needed). **OrderSuccess**: in `ItemCard` (~:739) branch on `isGiftDelivery(delivery)` BEFORE the `product_kind === "top_up"` test → render a gift card: title, `app_name — package_name`, 3 steps (проверьте уведомления/почту Steam; отправитель — бот-аккаунт, Steam покажет предупреждение; примите в течение 30 дней), and the artifact `message` as fallback text; non-gift deliveries untouched (assert via existing `pickArtifactDisplay` tests still passing). Commit `feat(miniapp): steam gift checkout and accept-the-gift delivery card`.

### Task M3: Rename to «Steam Игры» (display only)

**Files:**

- Modify: `scripts/seed/2026-09-03_steam_gifts.py` (brand translations ru «Steam Игры» / en "Steam Games" / uz "Steam o'yinlari"; the idempotent path must UPDATE drifted translation names — extend the managed-fields diff to brand translation names), re-run `--apply` against dev (postgres host port 5433) and verify
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` — `gifts.meta.title`, `gifts.hero.title` and any «Steam Гифты» copy → «Steam Игры» (en/uz equivalents); keep the gift-delivery subtitle wording («доставка подарком на профиль…») intact
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` — same display-name copy in the `gifts.*` keys from M1/M2
- Modify: `apps/admin/src/app/Layout.tsx` nav label «Steam Гифты» → «Steam Игры»; check `apps/admin/src/features/gifts/GiftsSettingsPage.tsx` headings
- Modify: `docs/product/flows/steam-gifts.md` + `docs/runbooks/steam-gifts.md` — one-line note that the customer-facing name is «Steam Игры» while the slug stays `steam-gifts`

Slug `steam-gifts`, route paths, `STEAM_GIFT_SKU_CODE`, env names: UNCHANGED. Steps: edit, re-run seed --apply, `pnpm --filter @yupay/i18n test` parity (or the repo's parity test), web+admin+miniapp test suites, prettier on docs. Commit `feat: rename the customer-facing section to «Steam Игры» (slug unchanged)`.
