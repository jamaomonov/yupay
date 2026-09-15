# Steam Gifts — fix everything that blocks a purchase

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (Steam Gifts is LIVE on prod).

**Goal:** Close every finding a UI/UX review and an accessibility audit classified as _blocks a purchase_ (or _blocks/badly degrades_ it). Nothing here is cosmetic — each item either produces an undeliverable order, charges a sum the buyer never saw, or leaves a required field unusable.

**Architecture:** Frontend + i18n only. No backend, no wire-contract change, no new dependency. The buyer still picks a country, the server still prices by zone and sends the zone's code to the supplier.

**Spec:** the two review reports (2026-09-04). This plan carries their findings; the reports themselves are the rationale.

## Global Constraints

- Every user-facing string exists in ru + en + uz. Several items DELETE keys; prefer reusing an existing key over inventing one, and reuse the mature panels' copy (`PurchasePanel.tsx` / `TopUp.tsx`) wherever the state already has established wording.
- Country names keep coming from `Intl.DisplayNames`, flags stay emoji. No flag host, no hardcoded country list.
- Money stays a string on the wire. Display-only changes.
- The miniapp is over its JS budget — no new dependencies; restructure what's there.
- Miniapp tests are node-env, NO jsdom/RTL: extract decisions into exported pure helpers and test those. Web has RTL and can render.
- TS strict, no `any`, no uncommented `as`.
- Conventional Commits; do NOT push, do NOT deploy. Never stage the pre-existing dirty files (`Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`).

## The shared copy (identical wording on both surfaces — ru canonical)

- Region step label: **«Страна Steam-аккаунта получателя»** (replaces the bare «Регион»).
- Region hint link: **«Как узнать?»**
- Region hint body: **«Попросите получателя открыть Steam → «Об аккаунте» → пункт «Страна» (store.steampowered.com/account). Регион подарка должен совпадать с этой страной — иначе Steam не даст принять подарок. Покупаете себе — смотрите свой профиль.»**
- The separate `regionWarning` line is DELETED on both surfaces — the label plus the hint now carry the rule.
- DLC note: **«Это дополнение (DLC). Оно заработает, только если у получателя уже есть основная игра.»** — append the parent game's name only if the API already exposes it; do not add a wire field for this.
- Edition-switch notice: **«Это издание продаётся только для: {country}»** — shown only when the edition switch actually moved the buyer's country.

---

### Task B1: Web — the blocking set

**Files:** `apps/web/src/components/gifts/GiftPurchasePanel.tsx`, `RegionHint.tsx`, `DlcBrowser.tsx`, `apps/web/src/app/[locale]/store/steam-gifts/[appId]/page.tsx`, `apps/web/src/lib/wallet-balance.ts` (maintenance state), `packages/i18n/locales/{ru,en,uz}/web.json`; tests alongside.

1. **FX down must block the sale, not guess.** `price_uzs` legitimately returns `null`; today the panel falls back to the USD figure (`:552-560`) and `canBuy` (`:322-323`) doesn't require a UZS total — so the buyer sees `12,99 $`, presses Buy and is sent to the acquirer for an unknown sum in soum. Require a non-null `price_uzs` for `canBuy`, and render the mature panels' dashed «цена временно недоступна» card in place of the amount (copy it from `PurchasePanel.tsx:548-553`). Also fix the wallet tile in this state: `walletTile` returns `noTotal`, whose string is «Выберите пакет» — wrong, the package IS chosen. Give it the FX-down wording instead.
2. **The region hint currently teaches the wrong thing.** It explains how to find _your own_ Steam country while the rule is the _recipient's_ — a buyer who follows it literally picks the wrong country and the gift cannot be redeemed. Apply the shared copy above: relabel the step, rewrite the hint, delete `regionWarning`.
3. **The edition switch silently moves the country.** `selectPackage` (`:191-211`) reassigns the country when the new edition isn't priced for the current one — good logic, invisible execution. Render the shared notice when, and only when, it actually moved.
4. **A DLC page never says it needs the base game.** `DlcBrowser` links each DLC to its own purchase page, which sells it with no such note — a delivered, unusable gift. Show the shared DLC note on a game page whose `type` marks it as DLC (`GiftAppOut.type` is already on the wire).
5. **Guest e-mail has no error UI at all** (`:590-610`, `emailValid` computed at `:321` and never rendered). A guest who mistypes sees only a dead button. Add the visible error, wire `aria-describedby` + `aria-invalid`, and add `autoComplete="email"`.
6. **The invite error isn't announced.** Give the error `id`, set `aria-describedby`/`aria-invalid` on the input.
7. **Payment tiles hide "техработы"/"скоро" in `title=`** (`:696-724`) — invisible to touch and to a screen reader. Adopt the mature grid's visible strip (`PurchasePanel.tsx:1894-1901`). Same for the wallet tile's maintenance state, which today keeps showing the balance caption as if payable (`:620-671`).

**Steps:** tests first for each behaviour (FX-down blocks Buy and shows the card; the wallet tile in FX-down shows the right copy; the edition-switch notice appears only when the country moved; a DLC page shows the note and a base game does not; an invalid guest email shows a visible error and blocks Buy; a maintenance tile shows visible text and no `title`) → fail → implement → pass → `pnpm --filter @yupay/web test -- --run`, `tsc --noEmit`, lint, locale parity. NEVER run `next build` on the host. Commit `fix(web): close the gift-purchase blockers found in review`.

---

### Task B2: Miniapp — the same blocking set

**Files:** `apps/miniapp/src/pages/GiftGame.tsx`, `apps/miniapp/src/components/gifts/{GiftBuyPanel,RegionPill,PaymentMethodGrid,RegionGuideSheet,DlcSheet}.tsx`, `apps/miniapp/src/components/ui/sheet.tsx`, `packages/i18n/locales/{ru,en,uz}/miniapp.json`; tests alongside.

1. **FX down must block the sale** — same as B1.1. `PackageOption.tsx:16-18` falls back to USD and `canBuy` doesn't require a UZS total. Use the app's existing `topup.priceUnavailable` treatment (`TopUp.tsx:1757-1763`).
2. **Region hint teaches the wrong account** — apply the shared copy; relabel the step; delete `regionWarning` (`GiftGame.tsx:803-805`).
3. **The edition switch silently moves the country** — `countryAfterPackageChange` (`:77-94`); render the shared notice when it moved.
4. **A DLC has no base-game note** — same as B1.4, on the miniapp game screen.
5. **The invite input has NO label association at all** (`GiftBuyPanel.tsx:66-79`): the `<label>` has no `htmlFor`, the input no `id`. This is the single required field in checkout and the web sibling already does it correctly with `useId()`. Fix it, and wire the error with `aria-describedby`/`aria-invalid`.
6. **Payment tiles hide their disabled reason in `title=`** (`PaymentMethodGrid.tsx:57-63`) — categorically unreachable inside Telegram's WebView, where there is no hover. Adopt `TopUp.tsx:1379-1390`'s visible strip. Note `WalletPayOption.tsx` in the same folder already does this correctly — match it.
7. **The shared sheet's close button announces hardcoded English "Close"** (`ui/sheet.tsx:66`) on a RU/UZ surface, in every sheet in the app. Route it through i18n.

**Steps:** tests first — but node-env only, so extract each decision into an exported pure helper (FX-down gate, "did the country move?", "is this a DLC?") and test those directly, mirroring `walletPayState`/`walletSubmitReady`/`nextSelectedMethodId`. → fail → implement → pass → `pnpm --filter @yupay/miniapp test -- --run`, typecheck, lint, locale parity, and confirm `TopUp`'s tests stay green (item 7 touches a shared component). Commit `fix(miniapp): close the gift-purchase blockers found in review`.
