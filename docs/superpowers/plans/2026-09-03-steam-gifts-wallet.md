# Steam Gifts — Pay from Wallet Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (feature is LIVE on prod — every change ships to real buyers).

**Goal:** Offer "pay from balance" in the Steam Gifts purchase panels on both surfaces, matching how it already works for ordinary products.

**Architecture:** No backend work — `WalletGateway` already accepts any `purpose="catalog"` UZS order, settles synchronously inside the intents call, and returns `intent_url: null`, which both gift checkout paths already handle. This is purely wiring the wallet tile, balance query and affordability gate into the two gift panels, reusing the components and i18n keys the normal-product panels already use.

**Tech Stack:** Next.js 15 App Router + TanStack Query (web), Vite + React 19 + wouter (miniapp).

**Spec:** none — this closes a deliberate v1 scope cut recorded in `docs/superpowers/plans/2026-09-03-steam-gifts.md` ("no promo field, no wallet pay, no qty"), at the operator's request (2026-09-03).

## Global Constraints

- **Backend is untouched.** `WalletGateway` (`apps/api/src/yupay/modules/payments/gateways/wallet.py`) refuses a guest (`order.user_id is None`), locks the `user_wallet` account `FOR UPDATE`, and 409s on insufficient funds with a `detail` reading `insufficient wallet balance: have … need …`. Do not modify any Python.
- **The wallet is the `provider` string `"wallet"`** passed to `POST /payments/intents` through the SAME checkout call both panels already make — no new branch in `lib/gift-checkout.ts::buyGift` (web) or `lib/orders.ts::performCheckout` (miniapp). Both already fall through to their non-redirect success path when `intent_url` is null.
- **Only `kind === "user_wallet"` balances count**, in the order's currency (gift orders are always `UZS`).
- **The UZS figure to compare against the balance is the selected region's `price_uzs`** (already on the DTO). When it is `null` (FX unavailable), the tile must render a non-selectable "unknown total" state rather than guessing — never compare against a USD number.
- **Both panels must honour `methodVisibility("wallet", providerStatus)`** so an admin can put the wallet into maintenance. (The web's _normal-product_ panel currently ignores this; that pre-existing gap is out of scope here — do not change `apps/web/src/components/store/PurchasePanel.tsx`.)
- **Reuse the existing i18n keys** (`payFromBalance*`/`successPaid*` in `web.json`; `topup.wallet*`/`topup.insufficient*`/`topup.paidFromBalance` in `miniapp.json`). Add a new key only when no existing one fits, and then in ru + en + uz together.
- TS strict, no `any`, no uncommented `as`. Money stays strings end-to-end; parse to a number only for the affordability comparison and display.
- Conventional Commits; do NOT push, do NOT deploy. Never stage the pre-existing dirty files (`Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`).

---

### Task W1: Web — wallet tile in the gift panel

**Files:**

- Modify: `apps/web/src/components/gifts/GiftPurchasePanel.tsx`
- Modify: `apps/web/src/lib/gift-checkout.ts` (surface the 409 detail; refresh the stale module docstring)
- Test: `apps/web/src/components/gifts/GiftPurchasePanel.test.tsx` (extend)

**Reference implementation to mirror** (read it first, it solved every edge case already): `apps/web/src/components/store/PurchasePanel.tsx` — `WALLET_METHOD_ID` (`:75`, deliberately kept OUT of `METHODS`), the `["wallet"]` query (`:1177-1182`), `walletTile`/`spendableBalance`/`canPayFromBalance` from `apps/web/src/lib/wallet-balance.ts`, the guest tile that opens the login modal (`:1789-1841`), the `invalidateQueries(["wallet"])` on completion (`:1480-1487`), and — critically — the reselect-effect early-return at `:1000-1010` that stops `selectActiveMethodId` from silently swapping a wallet selection for a card.

**Behaviour:**

- Wallet tile renders full-width above the existing acquirer grid, states `ready | short | guest | noTotal | unknown` from `walletTile({isLoggedIn, balance, total})`.
- `total` = `Number(selectedPrice.price_uzs)` when present, else `null` → `noTotal`.
- Guest: tile visible but not payable, copy `payFromBalanceGuest`, click opens the login modal (`useLoginModal`) — do NOT hide it, and never let a `Guest` token reach `provider: "wallet"`.
- `short`: show the existing top-up link to `/account/wallet/top-up`.
- Selecting the wallet sets `provider: "wallet"` on the existing `buyGift(...)` call; success (no `intent_url`) uses the panel's existing `router.push(trackHref)` path.
- Guard the reselect effect so a chosen wallet is never auto-swapped.
- `buyGift`: on a non-OK `payments/intents` response, parse the RFC7807 body and throw an error carrying its `detail`, so an "insufficient balance" 409 (possible even after the client check — the gateway re-checks under a row lock) reaches the buyer instead of the generic `buyError`. Match by structure, never by message text.

**Steps:** tests first (wallet tile shows for a logged-in user with enough balance; POST goes out with `provider: "wallet"`; a short balance disables paying and offers top-up; a guest sees the login prompt and cannot select it; a 409 surfaces its detail) → fail → implement → pass → `pnpm --filter @yupay/web test -- --run`, `tsc --noEmit`, lint, locale parity. NEVER run `next build` on the host. Commit `feat(web): pay for a Steam gift from the wallet balance`.

---

### Task W2: Miniapp — wallet option in the gift panel

**Files:**

- Create: `apps/miniapp/src/components/WalletPayOption.tsx` — extracted verbatim from the inline component in `apps/miniapp/src/pages/TopUp.tsx:198-270`
- Modify: `apps/miniapp/src/pages/TopUp.tsx` (use the extracted component; behaviour unchanged)
- Modify: `apps/miniapp/src/pages/GiftGame.tsx`, `apps/miniapp/src/components/gifts/GiftBuyPanel.tsx`, `apps/miniapp/src/components/gifts/PaymentMethodGrid.tsx` (stale docstring)
- Test: `apps/miniapp/src/pages/GiftGame.test.tsx` (extend — node env, exported pure logic only, no RTL)

**Reference implementation to mirror**: `apps/miniapp/src/pages/TopUp.tsx` — `WALLET_METHOD_ID` (`:158`), `PROVIDER_BY_METHOD_FULL` (`:164-167`), `useWallet()` + `groupBalancesByCurrency` (`:417-424`), the optimistic `walletEnough = true` while the balance is still loading (`:688-693`), `isMethodAvailable` resolving through the FULL map so `methodVisibility` is honoured (`:389-412`), the selection-keeping effect (`:463-471`), the pre-POST insufficient-funds toast (`:815-827`), and the paid-from-balance toast + `setLocation('/order/'+id)` (`:893-906`).

**Behaviour:** identical to W1 minus the guest case (the miniapp has no guests — Telegram `initData` auth). Extract the affordability decision into an exported pure helper so it can be unit-tested under this app's node-env convention (e.g. `walletPayState({balance, total, loading, visibility})`), and test it directly rather than rendering. Thread the wallet props from `GiftGame.tsx` into `GiftBuyPanel.tsx`, rendering `WalletPayOption` above `PaymentMethodGrid`. `performCheckout`/`useCheckout` need zero changes — they already treat `"wallet"` as availability-checked and already invalidate `["wallet"]`.

**Steps:** tests first for the extracted helper → fail → implement → pass → `pnpm --filter @yupay/miniapp test -- --run`, typecheck, lint, locale parity. Verify `TopUp`'s own wallet flow still passes its existing tests after the extraction. Commit `feat(miniapp): pay for a Steam gift from the wallet balance`.
