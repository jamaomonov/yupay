# Affiliate promo field on checkout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a buyer type a partner code on both checkouts, see the discount and the before/after total, and have the code reach the order.

**Architecture:** One self-contained component per surface, rendered between the payment-method block and the pay button. Each owns its input, its request, and its result; the host file gains about ten lines. Every number on screen comes from the server's preview response — the component never computes a price, and the pay button switches to the server's `total_after` once a code applies.

**Tech Stack:** Next.js 15 (web), Vite + React 19 (Mini App), TypeScript strict, next-intl v4 (web) / the Mini App's own `t()`, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**Previous plans:** `docs/superpowers/plans/2026-08-27-affiliate-core.md`, `docs/superpowers/plans/2026-08-28-affiliate-discount.md`

**Plan 3 of 7.** Steps 4–7 remain: partner auth and panel API, `apps/partners`, admin screens, infrastructure.

## Global Constraints

- TypeScript `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`. **No `any`.** No `as` casts except to narrow a known-shape JSON, with a comment.
- File length soft limit **300 LOC** for TS. Both host files are already far over it (`PurchasePanel.tsx` 2037, `TopUp.tsx` 2172) — that is precisely why the new code goes in its own file rather than inside them.
- **Every new user-facing string lands in `ru`, `en` and `uz` in the same commit.** CI fails if a locale is missing a key.
- Currency formatting through the surface's existing helper (`formatUzs` on web, `formatMoney` in the Mini App). Never string-concat a currency.
- `npx prettier --check .` must be clean on git-tracked files.
- Commit after every green test run. **Do not push or deploy** without an explicit instruction.

## What the server already provides

From plan 2, live on this branch:

- `POST /api/v1/affiliate/preview` — body `{code, currency, items: [{sku_id, qty, amount_usd?}]}`.
  Response: `{applicable, reason?, code?, percent?, currency, total_before, total_after, discount}`.
  **Signed-in only** (401/403 for a guest). Rate-limited per buyer.
- `POST /api/v1/orders` accepts `affiliate_code` and returns `discount_charged`.
- Every unusable code answers `applicable: false, reason: "unknown"` — nonexistent, disabled and suspended-partner are deliberately identical.

`reason` is one of: `unknown`, `guest`, `already_used`, `not_first_order`, `own_code`, `pending_coded_order`, `not_catalog`.

## Design decisions

**All displayed numbers come from the preview response.** The component shows `total_before` struck through and `total_after` beside it, and the host switches the pay button to `total_after`. If the client's own total ever disagreed with `total_before`, subtracting a server-computed discount from a client-computed total would show a price nobody will charge. One source, no drift.

**The field is visible, not hidden behind a "have a code?" toggle.** A visible promo field on checkout generally raises abandonment — people leave to hunt for a code — but this traffic arrives holding one. Recorded here so it stays a decision.

**A guest sees an invitation to sign in, not a failure.** The endpoint refuses guests by design, and half of all orders are guest orders. Rendering a dead field for half the traffic would be the worst of both.

**The code is applied optimistically to the button, not to the order body alone.** The host sends `affiliate_code` with the order; the server re-resolves it. If it has gone stale in the meantime the order is created at full price and `discount_charged` comes back zero — the component reads that and says so rather than silently charging more than the button promised.

## File Structure

**Created:**

| File                                                | Responsibility                                       |
| --------------------------------------------------- | ---------------------------------------------------- |
| `apps/web/src/components/store/PromoField.tsx`      | The web field: input, request, applied/error states. |
| `apps/web/src/components/store/PromoField.test.tsx` | Its tests.                                           |
| `apps/miniapp/src/components/PromoField.tsx`        | The Mini App field.                                  |
| `apps/miniapp/src/components/PromoField.test.tsx`   | Its tests.                                           |

**Modified:**

| File                                              | Change                                                                    |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| `apps/web/src/components/store/PurchasePanel.tsx` | Render the field; use `total_after` on the button; send `affiliate_code`. |
| `apps/miniapp/src/pages/TopUp.tsx`                | The same three.                                                           |
| `packages/i18n/locales/{ru,en,uz}/web.json`       | New `store.promo*` keys.                                                  |
| `packages/i18n/locales/{ru,en,uz}/miniapp.json`   | New `topup.promo*` keys.                                                  |

---

### Task 1: Message catalogues

Doing this first means neither component can be written against a key that does not exist, and the three locales cannot drift apart across commits.

**Files:**

- Modify: `packages/i18n/locales/{ru,en,uz}/web.json`
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json`

**Interfaces:**

- Produces the key set below. Both components consume it; the names are identical on the two surfaces apart from their namespace prefix.

| Key                     | ru                                                       | en                                                                    | uz                                                              |
| ----------------------- | -------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------- |
| `promoLabel`            | Промокод                                                 | Promo code                                                            | Promokod                                                        |
| `promoPlaceholder`      | Введите код                                              | Enter code                                                            | Kodni kiriting                                                  |
| `promoApply`            | Применить                                                | Apply                                                                 | Qo'llash                                                        |
| `promoChecking`         | Проверяем…                                               | Checking…                                                             | Tekshiryapmiz…                                                  |
| `promoRemove`           | Убрать                                                   | Remove                                                                | Olib tashlash                                                   |
| `promoApplied`          | Скидка {percent}%                                        | {percent}% off                                                        | {percent}% chegirma                                             |
| `promoSaved`            | Вы экономите {amount}                                    | You save {amount}                                                     | {amount} tejaysiz                                               |
| `promoSignIn`           | Войдите, чтобы применить промокод                        | Sign in to use a promo code                                           | Promokod uchun tizimga kiring                                   |
| `promoErrUnknown`       | Такой промокод не найден или больше не действует         | This code was not found or is no longer active                        | Bunday promokod topilmadi yoki amal qilmaydi                    |
| `promoErrAlreadyUsed`   | Вы уже активировали партнёрский промокод                 | You have already used a partner code                                  | Siz allaqachon hamkor promokodini ishlatgansiz                  |
| `promoErrNotFirstOrder` | Промокод действует только на первый заказ                | The code works on your first order only                               | Promokod faqat birinchi buyurtmaga amal qiladi                  |
| `promoErrOwnCode`       | Нельзя активировать собственный промокод                 | You cannot use your own code                                          | O'z promokodingizni ishlata olmaysiz                            |
| `promoErrPending`       | У вас уже есть неоплаченный заказ с промокодом           | You already have an unpaid order with a code                          | Sizda promokodli to'lanmagan buyurtma bor                       |
| `promoErrGeneric`       | Не удалось проверить промокод. Попробуйте ещё раз        | Could not check the code. Please try again                            | Promokodni tekshirib bo'lmadi. Qaytadan urinib ko'ring          |
| `promoDropped`          | Промокод больше не действует — заказ оформлен без скидки | The code is no longer valid — the order was placed without a discount | Promokod amal qilmaydi — buyurtma chegirmasiz rasmiylashtirildi |

`promoErrGeneric` covers the `not_catalog` reason too: a buyer can never see it from a catalog checkout, so it needs no sentence of its own.

- [ ] **Step 1: Add the keys to all six files**

Web keys go under the same object as `paymentTitle` (namespace `store`, per how `PurchasePanel` calls `t("paymentTitle")`). Mini App keys are flat with a `topup.` prefix, matching `t("topup.pay")`.

- [ ] **Step 2: Verify no locale is missing a key**

```bash
cd /Users/macbook_uz/Projects/yupay
node -e '
const fs=require("fs");
for (const ns of ["web","miniapp"]) {
  const load=(l)=>JSON.parse(fs.readFileSync(`packages/i18n/locales/${l}/${ns}.json`,"utf8"));
  const flat=(o,p="")=>Object.entries(o).flatMap(([k,v])=>typeof v==="object"&&v?flat(v,p+k+"."):[p+k]);
  const [ru,en,uz]=["ru","en","uz"].map(l=>new Set(flat(load(l))));
  const missing=[...ru].filter(k=>!en.has(k)||!uz.has(k));
  console.log(ns, missing.length?("MISSING: "+missing.join(", ")):"ok");
}'
```

Expected: `web ok` and `miniapp ok`.

- [ ] **Step 3: Format and commit**

```bash
npx prettier --write packages/i18n/locales
git add packages/i18n/locales
git commit -m "i18n(affiliate): promo field strings in all three locales"
```

---

### Task 2: The web field

**Files:**

- Create: `apps/web/src/components/store/PromoField.tsx`
- Create: `apps/web/src/components/store/PromoField.test.tsx`

**Interfaces:**

- Produces:

```typescript
export interface AppliedPromo {
  /** The code as the server normalised it — this is what checkout sends. */
  code: string;
  percent: string;
  /** Server-computed, in the order's currency. Minor-unit-safe strings. */
  totalBefore: string;
  totalAfter: string;
  discount: string;
}

export interface PromoFieldProps {
  locale: string;
  /** The cart, in the exact shape /affiliate/preview expects. */
  items: { sku_id: string; qty: number; amount_usd?: string }[];
  currency: string;
  isLoggedIn: boolean;
  /** Called whenever the applied promo changes, including to null. */
  onChange: (promo: AppliedPromo | null) => void;
}
```

- [ ] **Step 1: Write the failing tests**

Cover, with the network stubbed: an applied code renders the percent, the struck-through `total_before` and the `total_after`; each `reason` renders its own message; a guest sees the sign-in line and no input; removing a code calls `onChange(null)`; a failed request renders `promoErrGeneric` rather than throwing.

Follow the setup in `PurchasePanelWallet.test.tsx` for how this project stubs `fetch` and provides messages.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/web && pnpm vitest run src/components/store/PromoField.test.tsx`

- [ ] **Step 3: Write the component**

Requirements it must satisfy:

- `"use client"`.
- Guest: render only `promoSignIn`. No input, no request.
- Idle: label, text input (uppercase as typed), and an Apply button disabled while empty.
- Submitting: `POST /api/v1/affiliate/preview` through the same `apiFetch` helper the rest of the browser code uses, so auth headers and the surface header come for free.
- Applied: the code, `promoApplied` with the percent, `promoSaved` with the formatted discount, `total_before` struck through (`<s>` or `line-through`), `total_after` prominent, and a Remove control.
- Rejected: map `reason` to its message. An unmapped reason falls back to `promoErrGeneric` rather than rendering an empty box.
- Network/5xx: `promoErrGeneric`.
- Never throws. A promo field must not be able to break the checkout it sits in.
- Under 300 LOC.

- [ ] **Step 4: Green, lint, typecheck, commit**

```bash
cd apps/web && pnpm vitest run src/components/store/PromoField.test.tsx && pnpm tsc --noEmit && pnpm eslint src/components/store/PromoField.tsx
```

---

### Task 3: Wire the web checkout

**Files:**

- Modify: `apps/web/src/components/store/PurchasePanel.tsx`

Three edits, and no more:

- [ ] **Step 1: Hold the applied promo**

```typescript
const [promo, setPromo] = useState<AppliedPromo | null>(null);
```

- [ ] **Step 2: Render the field between the payment block and the button**

After the acquirer grid's closing `</div>` (around line 1880) and before the pay `<button>`:

```tsx
{
  selSku && orderTotalUzs !== null && (
    <PromoField
      locale={locale}
      items={[orderItem]}
      currency="UZS"
      isLoggedIn={isLoggedIn}
      onChange={setPromo}
    />
  );
}
```

`orderItem` is assembled inside the submit handler today. Lift its construction to a `useMemo` above the return so both the field and the handler use one definition — two places building the cart is how a preview and an order come to disagree.

`isLoggedIn` is likewise computed inside the handler (`user !== null && token !== null`); lift it too.

- [ ] **Step 3: Use the discounted total on the button and send the code**

The button renders `{t("pay")} · {selectedPriceLabel}`. When `promo` is set, show the formatted `promo.totalAfter` instead. Add to `orderBody`:

```typescript
...(promo ? { affiliate_code: promo.code } : {}),
```

- [ ] **Step 4: Tell the buyer if the code was dropped**

After the order response parses, the server's `discount_charged` is authoritative:

```typescript
const order = (await ord.json()) as { id: string; discount_charged?: string };
// A code that went stale between preview and checkout leaves the order at
// full price. Saying so beats silently charging more than the button showed.
if (promo && Number(order.discount_charged ?? 0) === 0) {
  setPromoDropped(true);
}
```

Render `promoDropped` as `t("promoDropped")` near the button.

- [ ] **Step 5: Full web test suite, lint, typecheck, commit**

```bash
cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm eslint src
```

The existing `PurchasePanel` tests must still pass untouched — the no-code path has to be unchanged.

---

### Task 4: The Mini App field

**Files:**

- Create: `apps/miniapp/src/components/PromoField.tsx`
- Create: `apps/miniapp/src/components/PromoField.test.tsx`

Same contract and the same states as Task 2, with the Mini App's own design language, its `t()` and its `formatMoney`. Deliberately **not** shared with the web component: the logic is ~30 lines of a request and a state machine, while the presentation and the catalogues differ, and these two surfaces do not share checkout components today.

One difference that matters: in the Mini App every buyer is signed in through Telegram, so the `isLoggedIn` branch is effectively dead. Keep the prop anyway rather than assuming — a signed-out state exists in the code (`write-access.ts`) and an assumption that quietly stops holding is worse than a branch that never renders.

- [ ] Steps mirror Task 2: failing tests → component → green → lint → commit.

---

### Task 5: Wire the Mini App checkout

**Files:**

- Modify: `apps/miniapp/src/pages/TopUp.tsx`

- [ ] **Step 1:** hold the applied promo in state.
- [ ] **Step 2:** render the field after the payment-method `<Step>` block (around line 1362) and before the pay button (line 1606).
- [ ] **Step 3:** the button renders `{t("topup.pay")} · {formatMoney(finalPrice, priceCode)}` — use the discounted total when a promo is applied. Send `affiliate_code` with the order, and read `discount_charged` back the same way.
- [ ] **Step 4:** `cd apps/miniapp && pnpm vitest run && pnpm tsc --noEmit && pnpm eslint src`, then commit.

---

### Task 6: Check the bundle budgets

**This step exists because nothing enforces it.** `CLAUDE.md` §10 records the budgets — web ≤ 180 KB gzipped JS per route, Mini App ≤ 120 KB — and also records that there is no CI check, which is how both surfaces drifted over (measured 2026-08-26: web 189 KB, Mini App 231 KB). Adding a component to the two heaviest routes without looking would be exactly the drift that produced those numbers.

- [ ] **Step 1: Build both and record the delta**

```bash
cd apps/web && pnpm build 2>&1 | tail -40
cd ../miniapp && pnpm build 2>&1 | tail -20
```

- [x] **Step 2: Report the numbers** — measured 2026-08-28, each against the
      same tree with only this plan's commits removed:

| Route                             | Before               | After          | Delta        | Budget                                     |
| --------------------------------- | -------------------- | -------------- | ------------ | ------------------------------------------ |
| web `/[locale]/store/[brandSlug]` | 150 kB First Load JS | 151 kB         | **+1 kB**    | 180 kB — under                             |
| Mini App single bundle            | 222.31 kB gzip       | 223.30 kB gzip | **+0.99 kB** | 120 kB — **already ~2× over, before this** |

The web checkout route is comfortably inside its budget, and `CLAUDE.md`'s
recorded 189 kB (2026-08-26) no longer reproduces — it now measures 151 kB.
Worth re-checking how that figure was taken before trusting either number.

The Mini App has no route splitting at all: one 722 kB JS chunk, 223 kB
gzipped, against a 120 kB budget. That is the pre-existing drift `CLAUDE.md`
already records, and this field adds 1 kB to it. Splitting it is the separate
piece of work the budget check is supposed to land after.

**One thing to know about building web on the host:** `apps/web/.next` is
bind-mounted into the dev container, so a host build corrupts the running
`next dev` and every page 500s. Stop the container first, and afterwards
`rm -rf apps/web/.next` and restart it.

**And the first web build failed** with a 500 from the local API on
`/catalog/products/mlbb-diamonds`, from a Redis read timeout — the build fires
hundreds of prerender requests at the dev stack at once. A plain `curl` of the
same path returned 200, and the retry succeeded. Transient dev-environment
load, not a code failure, but expect it.

State the before/after for the checkout routes plainly, including if they got worse. Do not add a CI check here — `CLAUDE.md` says to land that only after the Mini App split, or it blocks every PR.

⚠️ **Building `apps/web` on the host while the dev container is up corrupts `apps/web/.next`** — the directory is bind-mounted and shared with the container's `next dev`, and the result is a 500 on every dev page. Either stop the web container first, or accept that the fix afterwards is `rm -rf apps/web/.next` plus a container restart.

---

## Definition of Done for this plan

- [ ] `pnpm vitest run` green in both `apps/web` and `apps/miniapp`.
- [ ] `pnpm tsc --noEmit` and `pnpm eslint src` clean in both.
- [ ] All fifteen keys present in all six locale files.
- [ ] `npx prettier --check .` clean on git-tracked files.
- [x] Bundle sizes for both checkout routes measured and reported.
- [ ] A code applied on each surface visibly changes the pay button, and the order it creates carries the discount.
- [ ] Nothing pushed or deployed.

## Not in this plan

Steps 4–7: partner authentication and the panel API, `apps/partners`, admin screens, infrastructure. Nobody can obtain a code yet — an admin has to insert one by hand to exercise this end to end, which is expected until step 6.
