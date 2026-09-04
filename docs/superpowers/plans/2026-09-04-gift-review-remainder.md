# Steam Gifts — the rest of the review findings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (LIVE on prod).

**Goal:** Close everything the UI/UX review and accessibility audit found, apart from the purchase blockers (already shipped in `b1ef59f` + `8e4895f`) and the recipient-profile checker (deferred by the operator — it needs a server-side Steam Web API call, which is fine at our volume but is its own task).

**Architecture:** Frontend + i18n. One shared money-formatting change touches the whole storefront and gets its own task.

## Global Constraints

- Reuse the mature panels' solved patterns rather than inventing: `apps/web/src/components/store/PurchasePanel.tsx` and `apps/miniapp/src/pages/TopUp.tsx` already solve the CTA hint, the sticky bar, the confirm dialog and the maintenance strip.
- Every string in ru + en + uz. Several items DELETE keys.
- Miniapp is over its JS budget: no new dependencies; one item REMOVES a dependency use.
- Miniapp tests: node-env, NO jsdom/RTL — export pure helpers and test those. Web has RTL.
- TS strict, no `any`, no uncommented `as`. Money stays a string on the wire; formatting is display-only.
- Conventional Commits; do NOT push, do NOT deploy.
- **Run these tasks ONE AT A TIME.** A previous round ran two agents concurrently and one's `git stash` reverted the other's uncommitted work — `git stash`/`checkout` are worktree-wide even when the file sets are disjoint.
- Never stage the pre-existing dirty files (`Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`).

---

### Task C1: Money reads like money (storefront-wide)

**Why first:** it changes every price in both apps, so it should land before the per-surface work builds on it.

1. **UZS renders as a word, not an ISO code.** `Intl.NumberFormat(style:"currency", currency:"UZS")` gives `1 250 000 UZS` in ru (Latin code in a Cyrillic sentence) and `UZS 1,250,000` in en. Change the shared formatters — `apps/web/src/lib/seo.ts::formatUzs` and `apps/miniapp/src/lib/currency.ts::formatMoney` / `CURRENCY_SYMBOL` — to render «сум» / «soʻm» / «UZS» per locale. This lands storefront-wide, so check every caller renders sanely (grep both apps) and keep the grouping/spacing they already produce.
2. **Kill the second currency on the gift panel.** `GiftPurchasePanel` prints our UZS charge and a USD figure side by side (`price_usd`); the buyer can't tell which is charged (it is always UZS). Remove the USD figure from the price row and the per-package rows. Keep USD nowhere except as an explicit FX-down fallback — and note the blocker fix already blocks the sale in that state, so the fallback is now only informational.
3. **Catalogue card prices are «от».** Listing rows carry the _default-zone reference_ price (`gifts/routes.py` documents this); the game page computes the real per-package, per-country figure. Prefix the card price with «от» on both surfaces so a 1 250 000 → 1 410 000 jump doesn't read as bait.
4. Also in the miniapp: the same screen renders UZS two ways — `formatMoney` for the price and `formatBalance` (number + "UZS") for the wallet tile. Make them agree.

**Steps:** tests first (formatter output per locale; gift panel shows exactly one currency; card shows the «от» prefix) → fail → implement → pass → both suites, typecheck, lint, locale parity. Commit `fix(web,miniapp): price in sums, one currency, honest "from" prices`.

---

### Task C2: Web gift flow — the conversion set

**The one to get right first** (the reviewer's explicit "ship this first"): the Buy button must carry the amount and, when disabled, name the missing step. Today it reads «Купить» and greys out silently — a first-time buyer sees a dead button with nothing on screen explaining why, and the amount is ~500px up the page. `PurchasePanel.tsx:1243-1280` computes a `payHint` and renders it under the CTA; the CTA itself carries the total (`:1958-1964`). `TopUp.tsx:1519-1544` makes the disabled label the instruction. Mirror that: not payable → name the next required step; payable → «Купить · 1 250 000 сум»; pending → the existing spinner.

Then:

- **Sticky mobile checkout bar** — `PurchasePanel.tsx:2058-2103` has one (total + blocking reason, primary when payable, ghost that scrolls to the form when not, auto-hiding via `IntersectionObserver`); the gift page has none.
- **Confirm before charging** — ordinary top-ups get `ConfirmPurchaseModal`; the gift flow calls `handleBuy()` straight from the button, though a mistyped profile sends a paid game to a stranger irreversibly. Reuse the existing dialog: edition, country (flag + name), profile link, total.
- **Explain the product above the CTA** — `timeline` + `accept` currently sit _below_ the Buy button in 12px dim text, so the two sentences that explain the whole model are past the decision. Move them next to the invite field. `PurchasePanel.tsx:1983-1987` does exactly this with `afterPayNote`.
- **Invite label for self-purchase** — «Ссылка на профиль Steam получателя» tells a buyer purchasing for themselves they're in the wrong place. Add one inline line covering that case.
- **Show the pasted link as a clickable «Открыть профиль»** so the buyer can verify with their own eyes (this is the free half of the deferred profile-checker).
- **Region overflow** — the selected country can sit hidden behind «другой регион»; expand whenever the selection lands in the overflow, re-derived on change, not only at mount. And move unpriced countries into the overflow entirely, saying «нет цены для этого издания» once under the row instead of repeating it under up to eight pills at 10px.
- **The region hint expands inside the label row**, squeezing its panel to ~285px of 360px — move the expanded panel out of that flex row.
- **Invite error timing** — it fires on the first keystroke; show it on blur or after an idle debounce.
- **DLC pager** — add «N–M из TOTAL» (the total is already in state) and keep the pager mounted-but-disabled while loading instead of unmounting it under the thumb.
- **Search** — show the result/catalogue count, and make the empty state offer a route back («посмотрите горячие предложения»).
- **Desktop sticky panel** can outgrow the viewport and hide its own Buy button — cap with `max-h`/`overflow-y`.
- **Cuts:** `inviteGuideTitle` (restates the field label right above it); the «1 издание · 0 DLC» counter unless `packages_count > 1 || dlc_count > 0`.
- **a11y:** an unpriced edition shows a bare `"—"` — use real text; add `aria-live` so a price change after switching region/edition is announced; give the text-CTA triggers real touch-target padding; add `aria-expanded` to the DLC toggle.

**Steps:** tests first per behaviour → fail → implement → pass → web suite, `tsc --noEmit`, lint, locale parity. NEVER `next build` on the host. Commit `fix(web): make the gift CTA, confirm step and region control carry their own explanation`.

---

### Task C3: Miniapp gift flow — the same set, adapted

Everything in C2 that applies, plus the miniapp-specific findings:

- **Buy CTA with amount + reason**, and a fixed CTA above the nav band like `TopUp.tsx:1470` (the gift buy button is inline in the scroll flow).
- **Confirm dialog** — reuse `ConfirmPaymentDialog` (`TopUp.tsx:1551`).
- **Top-up link when the balance is short** — web offers one, `WalletPayOption` states the shortfall and offers no way to fix it.
- **Hot-strip cards carry no price** while the grid cards do — two card designs for the same content, two rows apart. Match the grid card.
- **A second back button**: a floating FAB is drawn unconditionally while Telegram's native BackButton is already wired for every non-root route, so the buyer sees two back arrows. `TopUp.tsx:911-923` scopes its FAB to the out-of-Telegram case — do the same.
- **Skeletons don't match the card shape** (`aspect-[3/4]` placeholders for a 16/9 image + text block), so content jumps on every load. `TopUp.tsx`'s `PackagesSkeleton` is the shape-aware precedent.
- **Contrast**: `text-white/40` measures 3.68–3.81:1 on this app's surfaces — below AA for the 10–12px captions it's used on. Raise to at least `white/50` for the region-price warning, the delivery-timeline caption and the catalogue card counters. Web already solved the same problem by re-tuning its token.
- **Drop the framer-motion page-entry fade** on both gift routes — it holds content back ~220ms on a surface already far over its JS budget; a CSS keyframe does the same for free.
- **Icon `alt` duplicates the visible label** in the payment grid — set `alt=""` (web already does).

**Steps:** node-env pure-helper tests → fail → implement → pass → miniapp suite, typecheck, lint, locale parity; confirm TopUp stays green (shared components). Commit `fix(miniapp): give the gift flow the same CTA, confirm step and contrast as top-up`.
