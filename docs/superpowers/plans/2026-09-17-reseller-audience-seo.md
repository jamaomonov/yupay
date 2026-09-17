# Reseller Site for Non-Technical Resellers + SEO/AEO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `reseller.yupay.uz` (app `apps/merchant`) speak to Telegram-channel resellers who fulfil orders by hand — no developer jargon on the manual-order path — while keeping the developer path, and make the site answer both audiences' questions in Google and in AI assistants.

**Architecture:** Copy-and-UI changes in the cabinet (i18n + four pages), a rewritten server-rendered landing built from `merchant.json` strings, three new server-rendered intent pages (`/telegram`, `/api`, `/faq`), and a technical SEO layer ported from `apps/web` (`seo.ts`, `robots.txt` route with AI crawlers + Content-Signal, `sitemap.ts` with hreflang, `JsonLd`, per-page `generateMetadata`, `llms.txt`). One footer link and one `llms.txt` section on the storefront. No API changes.

**Tech Stack:** Next.js 15 App Router (`apps/merchant`, `apps/web`), next-intl v4 (`localePrefix: "as-needed"`, same slugs in all locales), Tailwind v4, Vitest; i18n catalogs in `packages/i18n/locales/{ru,en,uz}/merchant.json` and `web.json`.

**Spec:** `docs/superpowers/specs/2026-09-17-reseller-seo-design.md` (SEO/AEO design — copy, page architecture, AEO rules, checklist) and `docs/superpowers/specs/2026-09-17-reseller-audience-review.md` (business review — cabinet journey, backlog). Where this plan's strings differ from the specs, **this plan wins** (owner rulings below).

## Global Constraints

- **Owner rulings (2026-09-17), override the specs:** (1) **no mention of deposit/balance top-up anywhere** in marketing copy — no step, no FAQ, no comparison; the prepaid model is named at most as «оплата с депозита», once, as a fact. (2) **No discounts, percentages, margin figures or "you earn N"** anywhere in marketing — say «оптовые цены» and nothing more; no `/prices` page, no price examples. (3) The offer page and its «Черновик» banner are not touched (legal text is the owner's). (4) No company requisites or manager names are invented — omit those lines. (5) Never write "sandbox" or "мгновенно".
- The cabinet's existing minimal hint («Депозит пока пуст… напишите в поддержку», `cabinet.balanceEmptyBody`) stays as is.
- `/docs/*` content is not rewritten; only metadata and one link are added.
- Vocabulary: reseller site = «Оптом» / «для перепродажи» / «оптовый поставщик»; never «партнёры» (that is partners.yupay.uz). Entity name everywhere: **YuPay**; the program: **YuPay Оптом**.
- Every new user-facing string lands in `ru`, `en`, `uz` in the same commit (CI parity check). Uzbek is Latin script with the codebase's `ʻ`/`ʼ` apostrophes as in the existing `uz/merchant.json`; write it natively, not as a transliteration of Russian.
- TS strict, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`; no `any`; no `as` except narrowing a known JSON/DOM shape with a comment. Server Components by default; the new pages are server-rendered (crawlers must see text without JS).
- Robots: AI crawlers are **welcomed** (never blocked); `/cabinet/*` and auth pages are `noindex`; `/catalog` is never disallowed.
- Commands: web `pnpm --filter @yupay/web exec …`, merchant `pnpm --filter @yupay/merchant exec …`; i18n parity `pnpm --filter @yupay/i18n test`; before pushing `pnpm exec prettier --check .`. Never run `next build` on the host while the dev docker stack is up.
- Commit messages: Conventional Commits, scope = app (`feat(merchant/landing): …`, `feat(merchant/seo): …`, `feat(web): …`). Never push or deploy without the owner's explicit command.

---

### Task 1: Cabinet without developer jargon + noindex

**Files:**

- Modify: `packages/i18n/locales/{ru,en,uz}/merchant.json` (`catalog.*`, `cabinet.*`, `orders.*`)
- Modify: `apps/merchant/src/app/[locale]/cabinet/catalog/[slug]/page.tsx` (SKU tile ~179–181, order box ~252–285)
- Modify: `apps/merchant/src/app/[locale]/cabinet/orders/page.tsx` (~148–185), `apps/merchant/src/app/[locale]/cabinet/orders/[id]/page.tsx` (~84–103, H1)
- Modify: `apps/merchant/src/app/[locale]/cabinet/layout.tsx` (`ACCOUNT` at ~32–38, the mobile strip ~145–160)
- Create: `apps/merchant/src/app/[locale]/cabinet/layout-metadata.ts` — no: Next only reads `metadata` from `layout.tsx`/`page.tsx`; since `cabinet/layout.tsx` is a client component, create `apps/merchant/src/app/[locale]/cabinet/noindex.tsx`? **Resolution:** add `export const metadata = { robots: { index: false, follow: false } }` to a new **server** wrapper `apps/merchant/src/app/[locale]/cabinet/layout.tsx` only if it is a server component; it is `"use client"` today, so instead move the client shell to `apps/merchant/src/app/[locale]/cabinet/Shell.tsx` and make `layout.tsx` a 6-line server component that exports the metadata and renders `<Shell>{children}</Shell>`.
- Test: `apps/merchant/src/lib/labels.test.ts` (new) for the order-title helper

**Interfaces:**

- Produces: `orderTitle(row: { sku_code: string; sku_name?: string | null; brand_name?: string | null }, fallback: string): string` in `apps/merchant/src/lib/labels.ts` — the human title of an order (`"PUBG Mobile · 660 UC"` when names are known, else the sku_code, else the fallback). Check `apps/merchant/src/lib/types.ts` `OrderRow`/`OrderDetail` for the fields the BFF returns (`sku_code`, maybe `sku_name`/`brand_name`); if the BFF returns only `sku_code`, the helper uses it and Task 1 notes in its report that a name needs `cabinet_orders.py` (out of scope here).

- [ ] **Step 1: Write the failing test**

`apps/merchant/src/lib/labels.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { orderTitle } from "./labels";

describe("orderTitle", () => {
  it("names the product, not the id", () => {
    expect(
      orderTitle({ sku_code: "pubgm-660", sku_name: "660 UC", brand_name: "PUBG Mobile" }, "x"),
    ).toBe("PUBG Mobile · 660 UC");
  });
  it("falls back to the sku code, then to the caller's fallback", () => {
    expect(orderTitle({ sku_code: "pubgm-660" }, "x")).toBe("pubgm-660");
    expect(orderTitle({ sku_code: "" }, "Заказ")).toBe("Заказ");
  });
});
```

Run: `pnpm --filter @yupay/merchant exec vitest run src/lib/labels.test.ts` → FAIL (`orderTitle` is not exported).

- [ ] **Step 2: Implement the helper**

Append to `apps/merchant/src/lib/labels.ts`:

```ts
/** The human name of an order: brand and package when the API sent them,
 *  the SKU code when it did not, the caller's fallback when even that is
 *  empty. A cabinet order's `merchant_order_id` is `manual-<uuid>` — a key,
 *  not a name — so it never appears as a title. */
export function orderTitle(
  row: { sku_code: string; sku_name?: string | null; brand_name?: string | null },
  fallback: string,
): string {
  const parts = [row.brand_name, row.sku_name].filter((p): p is string => Boolean(p));
  if (parts.length > 0) return parts.join(" · ");
  return row.sku_code || fallback;
}
```

Run the test → PASS.

- [ ] **Step 3: i18n**

In `merchant.json` (all three locales):

- Delete `catalog.apiHint` and `catalog.apiId`.
- Add `catalog.whatsNext`: ru `Код или подтверждение появится здесь и в «Заказах» — обычно через 1–2 минуты. Если выдать не получится, списание вернётся на депозит автоматически.`; en `The code or confirmation appears here and under "Orders" — usually within 1–2 minutes. If delivery fails, the charge returns to your deposit automatically.`; uz `Kod yoki tasdiq shu yerda va «Buyurtmalar»da paydo boʻladi — odatda 1–2 daqiqada. Chiqmasa, yechilgan pul depozitga oʻzi qaytadi.`
- Add `cabinet.groupDevelopers`: ru `ДЛЯ РАЗРАБОТЧИКОВ`, en `FOR DEVELOPERS`, uz `DASTURCHILAR UCHUN`.
- Add `orders.title` stays; add `orders.idLabel`: ru `Номер заказа`, en `Order number`, uz `Buyurtma raqami`; `orders.technical`: ru `Технические данные`, en `Technical details`, uz `Texnik maʼlumotlar`.
- `settings.keysTitle` stays (it is inside the developers group now).

- [ ] **Step 4: Catalog page**

`cabinet/catalog/[slug]/page.tsx`:

- Remove the `<p>` with `{t("apiId")}: {sku.sku_id.slice(0, 8)}…` from the SKU tile.
- Replace the last `<p …>{t("apiHint")}: sku_id {selected.sku_id}</p>` with `<p className="text-tx-dim mt-3 text-[12px] leading-relaxed">{t("whatsNext")}</p>`.
- After placing: `<span className="font-mono">{placed.status}</span>` → `orderStatusLabel(placed.status, tOrders)` (import from `@/lib/labels`; keep the link «Открыть заказ»).

- [ ] **Step 5: Orders list and detail**

`orders/page.tsx`: the first column shows `orderTitle(row, tOrders("title"))` as the link text (bold, not mono), and `row.merchant_order_id` under it in `text-tx-dim text-xs` only when it does not start with `manual-`. Keep every other column.

`orders/[id]/page.tsx`: H1 = `orderTitle(order, t("title"))`; directly under it a `text-tx-dim text-xs` line `{t("idLabel")}: {order.merchant_order_id}` shown only when the id does not start with `manual-`. Move the two `<dt>` rows «Наш ID» and «SKU» into a `<details>` block titled `{t("technical")}` at the bottom of the card (keep their copy buttons). The delivery artifact block is unchanged in this task.

- [ ] **Step 6: Navigation**

`cabinet/layout.tsx`: split `ACCOUNT` into `ACCOUNT = [navOrders, navTransactions, navSettings]` and `DEVELOPERS = [navWebhooks, navDocs]`; render `DEVELOPERS` under a new group heading `t("groupDevelopers")` in the sidebar (same markup as `groupAccount`); in the mobile strip render only `ACCOUNT` (webhooks and docs are reachable from the sidebar/settings on desktop and from the docs link in the landing header). Then extract the client shell into `cabinet/Shell.tsx` and make `cabinet/layout.tsx` a server component:

```tsx
import type { Metadata } from "next";

import { Shell } from "./Shell";

/** The cabinet is a signed-in, client-rendered surface: never indexed. */
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function CabinetLayout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
```

- [ ] **Step 7: Checks and commit**

Run: `pnpm --filter @yupay/merchant exec tsc --noEmit && pnpm --filter @yupay/merchant exec vitest run && pnpm --filter @yupay/merchant exec eslint src && pnpm --filter @yupay/i18n test && pnpm exec prettier --check apps/merchant/src packages/i18n/locales`. `rg -n "apiHint|apiId|sku_id" apps/merchant/src/app/\[locale\]/cabinet` must show `sku_id` only inside the order body/`<details>`.

```bash
git add apps/merchant/src packages/i18n/locales
git commit -m "feat(merchant/cabinet): no developer jargon on the manual order path, cabinet noindex"
```

---

### Task 2: Landing rewrite for both audiences

**Files:**

- Modify: `apps/merchant/src/app/[locale]/page.tsx` (whole page body)
- Create: `apps/merchant/src/components/landing/CabinetMock.tsx` (server component, pure markup)
- Modify: `packages/i18n/locales/{ru,en,uz}/merchant.json` (`meta.*`, `landing.*`, `auth.acceptOffer`, `offer.title`)

**Interfaces:**

- Consumes: `countBrands()` from `@/lib/brands` (already used).
- Produces: anchors `#how`, `#developers`, `#faq` on `/`; links to `/telegram`, `/api`, `/faq` (Task 4 creates them — link now, they 404 for one commit only within this branch).

- [ ] **Step 1: Strings (ru authoritative; en/uz below)**

Replace the whole `landing` object and `meta` in `ru/merchant.json`:

```json
"meta": {
  "title": "Пополнения игр оптом для перепродажи — YuPay",
  "description": "Оптовый поставщик пополнений игр, ваучеров и подарочных карт в Узбекистане. Заказ с телефона из кабинета или через API, проверка ID игрока до оплаты, выдача 1–2 минуты."
},
"landing": {
  "heading": "Оптовые цены на пополнения игр. Для тех, кто продаёт в Telegram.",
  "subheading": "PUBG UC, алмазы Mobile Legends и Free Fire, Steam, Roblox, Discord, Telegram Premium — по оптовым ценам. Заказ из кабинета с телефона, ID игрока проверяем до оплаты, выдача обычно за 1–2 минуты.",
  "micro": "без договора · без минимального объёма · каталог с ценами открывается сразу после регистрации",
  "answer": "YuPay Оптом — оптовый поставщик пополнений игр, ваучеров и подарочных карт для реселлеров в Узбекистане и СНГ. Вы покупаете PUBG UC, алмазы Mobile Legends и Free Fire, Steam, Roblox, Discord и Telegram Premium по оптовым ценам и перепродаёте своим покупателям. Заказ делается из кабинета с телефона или одним запросом к HTTP API, ID игрока проверяется до оплаты и показывает никнейм, выдача автоматическая и занимает обычно 1–2 минуты, оплата с депозита. Если выдать товар не удалось, а деньги вернулись от поставщика, списание возвращается автоматически.",
  "ctaPrimary": "Создать аккаунт",
  "ctaSecondary": "Как это работает",
  "navDocs": "Разработчикам",
  "navTelegram": "Для Telegram-каналов",
  "navFaq": "Вопросы",
  "login": "Войти",
  "brandsCount": "{count} брендов в каталоге",
  "metricBrands": "брендов",
  "metricAuto": "автоматическая выдача",
  "metricCheck": "проверка ID до оплаты",
  "forWhoHeading": "Кому это подходит",
  "forWhoTgTitle": "Продаю в Telegram-канале",
  "forWhoTgBody": "Заказ из кабинета с телефона: выбрали игру, ввели ID игрока, увидели никнейм, получили код. Кода писать не надо.",
  "forWhoTgCta": "Как это работает",
  "forWhoDevTitle": "У меня свой сайт или бот",
  "forWhoDevBody": "Шесть эндпоинтов, HMAC-подпись, идемпотентность по вашему merchant_order_id, вебхуки. OpenAPI 3.1 открыт.",
  "forWhoDevCta": "Обзор API",
  "stepsHeading": "Запуск в 3 шага",
  "step1Title": "Регистрация",
  "step1Body": "Почта и пароль. Каталог с вашими ценами открывается сразу.",
  "step2Title": "Выбрали товар и ввели ID",
  "step2Body": "Проверяем ID и показываем никнейм до того, как что-то спишется.",
  "step3Title": "Получили код",
  "step3Body": "Обычно 1–2 минуты. Не выдалось — списание вернётся само.",
  "sectionsHeading": "Что есть в каталоге",
  "sectionTopups": "Пополнения игр",
  "sectionTopupsBody": "PUBG Mobile, Mobile Legends, Free Fire, Roblox, Standoff 2 — зачисление на аккаунт игрока по ID.",
  "sectionVouchers": "Ваучеры и карты",
  "sectionVouchersBody": "Steam, Discord, Roblox и подарочные коды — выдача кода в кабинете и через API.",
  "sectionGifts": "Игры в подарок",
  "sectionGiftsBody": "Игры на профиль Steam — следующая категория программы.",
  "soon": "СКОРО",
  "wrongIdHeading": "Что если ID введён неверно",
  "wrongIdBody": "ID проверяется до оплаты: кабинет показывает никнейм владельца аккаунта, и до вашего подтверждения ничего не списывается. Если проверить не удалось, вы увидите это прямо — «не смогли проверить», а не «всё в порядке».",
  "devHeading": "Есть свой сайт или бот? Шесть эндпоинтов — и всё.",
  "dev1Title": "Автоматическая выдача",
  "dev1Body": "POST /merchant/v1/orders — товар уходит покупателю без участия человека. Статус и выданный код читаются через GET /merchant/v1/orders/{merchant_order_id}.",
  "dev2Title": "Идемпотентность по вашему ключу",
  "dev2Body": "Ключ — ваш собственный merchant_order_id. Повтор того же запроса при таймауте не создаёт второй заказ и не списывает дважды.",
  "dev3Title": "Вебхуки с подписью",
  "dev3Body": "Результат выдачи приходит на ваш URL, каждая доставка подписана, подпись проверяется по сырым байтам тела. Опрашивать статус в цикле не нужно.",
  "dev4Title": "Проверка ID игрока до заказа",
  "dev4Body": "POST /merchant/v1/validate/player возвращает никнейм до того, как вы спишете деньги с покупателя. Три вердикта: valid, invalid, error — и error означает «не смогли проверить», а не «ID плохой».",
  "dev5Title": "Автоматический возврат",
  "dev5Body": "Если выдать не удалось и деньги вернулись от поставщика — списание возвращается само, без письма в поддержку.",
  "devTest": "Тестируйте на самом дешёвом номинале — заказы настоящие, суммы копеечные.",
  "devSpec": "Спецификация OpenAPI 3.1",
  "devLinks": "Быстрый старт · Авторизация · Вебхуки · Ошибки",
  "compareHeading": "Чем мы отличаемся от других поставщиков",
  "compare1": "Узбекистан: цены и расчёты в сумах у вашего покупателя, поддержка на русском и узбекском.",
  "compare2": "ID игрока проверяется до оплаты и показывает никнейм.",
  "compare3": "Автоматический возврат на депозит, если выдача не удалась и деньги вернулись.",
  "compare4": "Открытая спецификация API — клиент генерируется на любом языке.",
  "compare5": "Самостоятельная регистрация по почте: без заявки и ожидания менеджера.",
  "compare6": "Мы сами торгуем этим в розницу — yupay.uz.",
  "faqHeading": "Вопросы, начистоту",
  "faqAll": "Все вопросы",
  "trustHeading": "О компании",
  "trustRetail": "Мы сами торгуем этим в розницу — yupay.uz. Оптовая программа — тот же каталог и та же выдача.",
  "trustOffer": "Договор оптовой поставки (оферта)",
  "supportHeading": "Остались вопросы?",
  "supportBody": "Напишите нам — поможем с подключением.",
  "supportCta": "Написать в поддержку",
  "badge": "оптом"
}
```

Also: `auth.acceptOffer` → ru `Я принимаю условия договора оптовой поставки (оферты)`, `offer.title` → ru `Договор оптовой поставки (оферта)`.

**en** — translate the ru block 1:1 (developer audience, precision over tone); `meta.title` `Wholesale game top-ups for resellers — YuPay`; `heading` `Wholesale prices on game top-ups. For people who sell on Telegram.`; `badge` `wholesale`; `auth.acceptOffer` `I accept the wholesale supply agreement (offer)`; `offer.title` `Wholesale supply agreement (offer)`.

**uz** — native Latin; the hero/steps/forWho/dev/FAQ strings are in the design doc §5.1–5.5 (`docs/superpowers/specs/2026-09-17-reseller-seo-design.md`) **with these substitutions**: no `rozitsadan arzon` / `10–25 %` (say `optom narxda`), no deposit line in the steps (`step2Title` `Tovarni tanlab, ID kiritasiz`, `step2Body` `ID ni tekshirib, nikni koʻrsatamiz — hech narsa yechilmasdan oldin.`, `step3Title` `Kod keldi`, `step3Body` `Odatda 1–2 daqiqa. Chiqmasa — yechilgan pul oʻzi qaytadi.`); `meta.title` `Oʻyin toʻldirishlar optom — qayta sotish uchun | YuPay`; `badge` `optom`; `auth.acceptOffer` `Optom yetkazib berish shartnomasi (oferta) shartlarini qabul qilaman`; `offer.title` `Optom yetkazib berish shartnomasi (oferta)`. Strings the doc lacks (`answer`, `micro`, `metricCheck`, `wrongId*`, `compare*`, `trust*`, `whatsNext`, `nav*`) — write them natively in the same register.

- [ ] **Step 2: The cabinet mock-up**

`apps/merchant/src/components/landing/CabinetMock.tsx` — a static, decorative, server-rendered illustration of the cabinet (no data fetch, no numbers, no prices): a sidebar with «Каталог · Заказы · Настройки», a brand grid of six tiles (PUBG Mobile, Mobile Legends, Free Fire, Roblox, Steam, Discord), and an order card showing the ID field with a green check line `✓ Аккаунт: Neo_Uz` and a status pill «Выдан». Labels come from a small `labels` prop typed `{ catalog; orders; settings; account; delivered }` so the page passes translated strings; mark the whole block `aria-hidden` with a visually-hidden caption `t("mockCaption")` (add the key: ru `Так выглядит кабинет: каталог, проверка ID игрока, статус заказа`, en `What the cabinet looks like: catalog, player-ID check, order status`, uz `Kabinet shunday koʻrinadi: katalog, oʻyinchi ID tekshiruvi, buyurtma holati`). Tailwind only, ≤ 120 lines.

- [ ] **Step 3: Page body**

Rewrite `apps/merchant/src/app/[locale]/page.tsx` in this order, keeping the existing header/footer shells and classes: header nav = `navTelegram` → `/telegram`, `navFaq` → `/faq`, `navDocs` → `/api` (small link), «Войти», «Создать аккаунт»; badge `t("badge")` instead of `reseller`. Sections: hero (H1, subheading, micro line, CTAs `/register` and `#how`, metrics `brands+ / metricAuto / metricCheck`, `<CabinetMock>` on the right); the answer paragraph (`<p className="text-tx-mute …">{t("answer")}</p>` immediately under the hero — this is the sentence assistants lift, keep it before every other block); «Кому это подходит» two cards (`forWhoTg*` → `#how`, `forWhoDev*` → `/api`); `#how` «Запуск в 3 шага»; catalog sections (unchanged markup); `wrongId*` card; `#developers` section with the five `dev*` cards, `devTest`, and a links row (`devSpec` → `https://api.yupay.uz/merchant/openapi.json`, plus `/docs/quickstart`, `/docs/authentication`, `/docs/webhooks`, `/docs/errors`); `compareHeading` as a 6-row list (no competitor names, no prices); `#faq` with the first five FAQ entries from Task 4's `faq` namespace (import the same strings — `t("faq.q1")`… — so the two pages never diverge; the landing shows q1–q5 and a `faqAll` link to `/faq`); trust (`trustRetail` with a link to `https://yupay.uz`, `trustOffer` → `/offer`); support. Delete `SNIPPET`, `SNIPPET_TITLE`, `CodeWindow` import.

- [ ] **Step 4: Checks and commit**

Run: `pnpm --filter @yupay/merchant exec tsc --noEmit && pnpm --filter @yupay/merchant exec eslint src && pnpm --filter @yupay/i18n test && pnpm exec prettier --check apps/merchant/src packages/i18n/locales`. Then `rg -n "партнёр|reseller\b|для партнёров|скидк|%|депозит" packages/i18n/locales/ru/merchant.json` — the only `депозит` hits allowed are `cabinet.balanceEmpty*`, `catalog.depositAfter`, `catalog.whatsNext`, `landing.answer`, `landing.compare3`, `landing.dev5Body`, `landing.step3Body` (none of them a how-to); `%` and `скидк` must not appear in `landing`/`faq`/`meta`.

```bash
git add apps/merchant/src packages/i18n/locales
git commit -m "feat(merchant/landing): speak to Telegram resellers first, developers below the fold"
```

---

### Task 3: Technical SEO layer (merchant) + storefront links

**Files:**

- Create: `apps/merchant/src/lib/seo.ts`, `apps/merchant/src/lib/seo.test.ts`, `apps/merchant/src/app/robots.txt/route.ts`, `apps/merchant/src/app/sitemap.ts`, `apps/merchant/src/app/llms.txt/route.ts`, `apps/merchant/src/components/JsonLd.tsx`
- Modify: `apps/merchant/src/app/[locale]/layout.tsx` (metadata: `metadataBase`, `alternates`, `openGraph`, remove the blanket `robots`), `apps/merchant/src/app/[locale]/page.tsx` (`generateMetadata` + JSON-LD), `apps/merchant/src/app/[locale]/docs/**/page.tsx` and `docs/layout.tsx` (per-page titles, `TechArticle`, «← Обзор API» link), `apps/merchant/src/app/[locale]/{login,register,forgot,reset,confirm,offer}/page.tsx` (`NOINDEX` on auth pages; `offer` indexable with its own title)
- Modify: `apps/web/src/components/Footer.tsx` (+ `web.json` `footer.wholesale` ×3), `apps/web/src/app/llms.txt/route.ts` («Для бизнеса» section), `apps/web/src/app/[locale]/layout.tsx` (`Organization` `@id`)
- Modify: `apps/merchant/src/middleware.ts` matcher — exclude `llms.txt`/`robots.txt`/`sitemap.xml` if the current pattern (`/((?!api|_next|_vercel|.*\\..*).*)`) does not already skip dotted paths (it does — verify with the existing `middleware.test.ts` and add a case).

**Interfaces:**

- Produces: `SITE = "https://reseller.yupay.uz"`, `localeUrl(locale, path)`, `alternates(locale, path)` (canonical + `languages` ru/en/uz + `x-default`), `ROBOTS`, `NOINDEX`, `ogLocale(locale)` — copied from `apps/web/src/lib/seo.ts` with the site constant changed; `JsonLd({ data })` copied from `apps/web/src/components/JsonLd.tsx`; `SEO_PATHS = ["", "/telegram", "/api", "/faq", "/docs", "/docs/quickstart", "/docs/authentication", "/docs/webhooks", "/docs/errors", "/offer"]` exported from `seo.ts` and used by both `sitemap.ts` and `llms.txt`.

- [ ] **Step 1: Failing tests**

`apps/merchant/src/lib/seo.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { SEO_PATHS, alternates, localeUrl } from "./seo";

describe("reseller seo helpers", () => {
  it("builds locale urls with as-needed prefixes", () => {
    expect(localeUrl("ru", "/api")).toBe("https://reseller.yupay.uz/api");
    expect(localeUrl("uz", "/api")).toBe("https://reseller.yupay.uz/uz/api");
    expect(localeUrl("en")).toBe("https://reseller.yupay.uz/en");
  });
  it("emits canonical, three languages and x-default", () => {
    const a = alternates("uz", "/telegram");
    expect(a.canonical).toBe("https://reseller.yupay.uz/uz/telegram");
    expect(a.languages).toMatchObject({
      ru: "https://reseller.yupay.uz/telegram",
      en: "https://reseller.yupay.uz/en/telegram",
      uz: "https://reseller.yupay.uz/uz/telegram",
      "x-default": "https://reseller.yupay.uz/telegram",
    });
  });
  it("never lists the cabinet or auth pages", () => {
    expect(
      SEO_PATHS.some((p) => p.startsWith("/cabinet") || p === "/login" || p === "/register"),
    ).toBe(false);
  });
});
```

Run → FAIL (module missing).

- [ ] **Step 2: Implement `seo.ts`, `JsonLd.tsx`, `robots.txt`, `sitemap.ts`, `llms.txt`**

`seo.ts`: copy `SITE`, `ROBOTS`, `NOINDEX`, `localeUrl`, `pathFor`, `alternates`, `ogLocale` from `apps/web/src/lib/seo.ts` (same semantics; `SITE = "https://reseller.yupay.uz"`), plus `export const SEO_PATHS = […]` as above. Run the test → PASS.

`robots.txt/route.ts`: copy `apps/web/src/app/robots.txt/route.ts` verbatim, then change `Host`/`Sitemap` to `https://reseller.yupay.uz` and `DISALLOW = ["/api/", "/cabinet/", "*/cabinet/", "/login", "*/login", "/register", "*/register", "/reset", "*/reset", "/forgot", "*/forgot", "/confirm", "*/confirm"]`. Keep the AI-crawler list and `Content-Signal: search=yes, ai-input=yes, ai-train=no` untouched.

`sitemap.ts`: for each path in `SEO_PATHS` × each locale, `{ url: localeUrl(locale, path), lastModified: <today truncated to the day>, changeFrequency: "weekly", priority: path === "" ? 1 : 0.7, alternates: { languages: languagesFor(path) } }` — copy `languagesFor` from `apps/web/src/app/sitemap.ts`; `export const revalidate = 3600`.

`llms.txt/route.ts`: `GET()` returning `text/markdown; charset=utf-8` with this body (ru; the brand list built from `countBrands()`'s source if it exposes names, else the static list below):

```
# YuPay Оптом

> Обновлено: 2026-09.

> YuPay Оптом (reseller.yupay.uz) — оптовая закупка пополнений игр, ваучеров и подарочных карт для перепродажи. Аудитория: владельцы Telegram-каналов и магазинов в Узбекистане, России и СНГ, а также разработчики, которым нужен API автоматического пополнения. Регистрация по e-mail, оплата с депозита, ID игрока проверяется до оплаты и возвращает никнейм, выдача автоматическая — обычно 1–2 минуты, при неудачной выдаче списание возвращается автоматически. Заказ делается из кабинета или через подписанный HTTP API. Это НЕ партнёрская программа partners.yupay.uz (там 2 % с заказов приведённых покупателей).

## Что можно закупать
- PUBG Mobile UC · Mobile Legends (global и RU) · Free Fire · Roblox · Standoff 2 · Steam · Discord · Genshin Impact · Honkai: Star Rail · Telegram Premium · Telegram Stars · Magic Chess: Go Go · Blood Strike · Whiteout Survival · Delta Force · Arena Breakout · Oxide: Survival Island

## Для разработчиков
- [Обзор API](https://reseller.yupay.uz/api)
- [Быстрый старт](https://reseller.yupay.uz/docs/quickstart)
- [Авторизация: HMAC-SHA256](https://reseller.yupay.uz/docs/authentication)
- [Вебхуки](https://reseller.yupay.uz/docs/webhooks)
- [Ошибки: RFC 7807](https://reseller.yupay.uz/docs/errors)
- OpenAPI 3.1: https://api.yupay.uz/merchant/openapi.json
- Эндпоинты: GET /merchant/v1/me · GET /catalog · POST /orders · GET /orders/{merchant_order_id} · POST /validate/player · GET /transactions

## Ключевые страницы
- [Для Telegram-каналов](https://reseller.yupay.uz/telegram)
- [Вопросы](https://reseller.yupay.uz/faq)
- [Договор оптовой поставки (оферта)](https://reseller.yupay.uz/offer)

## Заметки
- Языки: ru (основной), uz (латиница), en — у каждой страницы hreflang.
- Розничный магазин того же бизнеса: https://yupay.uz
```

- [ ] **Step 3: Metadata per page**

`[locale]/layout.tsx`: keep `title`/`description` as defaults, add `metadataBase: new URL(SITE)`, `alternates: alternates(locale)`, `openGraph: { type: "website", siteName: "YuPay", locale: ogLocale(locale), url: localeUrl(locale) }`, and **remove** the blanket `robots` (each page sets its own; the cabinet layout from Task 1 sets `NOINDEX`). Landing `page.tsx`: `generateMetadata` with `meta.title`/`meta.description`, `alternates(locale, "")`, `robots: ROBOTS`; render `<JsonLd data={…}>` with `Organization` (`"@id": "https://yupay.uz/#organization"`, `name: "YuPay"`, `url: "https://yupay.uz"`, `sameAs: ["https://reseller.yupay.uz", "https://partners.yupay.uz"]`), `WebSite` (`url: SITE`), `Service` (`name: "YuPay Оптом"`, `serviceType: "Wholesale digital goods supply"`, `areaServed: ["UZ", "RU", "KZ"]`, `provider: { "@id": "https://yupay.uz/#organization" }`, `url: SITE`) and `FAQPage` with the five landing FAQ entries. Auth pages: `robots: NOINDEX`. `/offer`: own title (`offer.title`), `ROBOTS`. `/docs/*`: `generateMetadata` per page — title `${sectionTitle} — YuPay Merchant API` using the existing `docs.*` keys (`introTitle`, `quickTitle`, `authTitle`, `errorsTitle`, `webhooksTitle`; `/docs/api/[operation]` uses the operation summary; `/docs/schemas/[name]` the schema name), `alternates`, `TechArticle` JSON-LD with `dateModified` = build date; add a «← Обзор API» link to `/api` in `DocsShell`'s header (find the brand link prop `brand={pathFor(locale, "")}` and add a sibling link with `t("docs.apiOverview")` — add the key ×3: ru `Обзор API`, en `API overview`, uz `API haqida`).

- [ ] **Step 4: Storefront**

`apps/web/src/components/Footer.tsx`: `const RESELLER_URL = process.env.NEXT_PUBLIC_RESELLER_URL ?? "https://reseller.yupay.uz";` and a `<FooterLink href={RESELLER_URL} external>{t("wholesale")}</FooterLink>` next to the partners link; `web.json` `footer.wholesale`: ru `Оптом / для перепродажи`, en `Wholesale`, uz `Optom / qayta sotish uchun` (check the footer's namespace — `t` there may be `footer` or `common`; use whichever the partners link uses). `apps/web/src/app/llms.txt/route.ts`: add before the legal section:

```
## Для бизнеса
- [YuPay Оптом](https://reseller.yupay.uz): оптовая закупка пополнений, ваучеров и подарочных карт для перепродажи. Проверка ID игрока до оплаты, выдача 1–2 минуты.
- [Merchant API](https://reseller.yupay.uz/api): HTTP API автоматического пополнения — 6 эндпоинтов, HMAC-подпись, вебхуки, проверка ID игрока. OpenAPI: https://api.yupay.uz/merchant/openapi.json
- [Партнёрская программа](https://partners.yupay.uz): 2% с заказов приведённых покупателей (это другой продукт — не оптовая закупка).
```

`apps/web/src/app/[locale]/layout.tsx` (~line 110, the `Organization` JSON-LD): add `"@id": "https://yupay.uz/#organization"`. Update the storefront's `markdown-paths.test.ts`/`llms` tests only if they snapshot the file.

- [ ] **Step 5: Checks and commit**

Run: `pnpm --filter @yupay/merchant exec tsc --noEmit && pnpm --filter @yupay/merchant exec vitest run && pnpm --filter @yupay/merchant exec eslint src && pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/web exec vitest run src/lib src/components src/app && pnpm --filter @yupay/i18n test && pnpm exec prettier --check apps/merchant apps/web/src packages/i18n/locales`.

```bash
git add apps/merchant/src apps/web/src packages/i18n/locales
git commit -m "feat(merchant/seo): robots, sitemap, per-page metadata, JSON-LD, llms.txt; storefront links to the wholesale program"
```

---

### Task 4: Intent pages `/telegram`, `/api`, `/faq`

**Files:**

- Create: `apps/merchant/src/app/[locale]/telegram/page.tsx`, `apps/merchant/src/app/[locale]/api/page.tsx`, `apps/merchant/src/app/[locale]/faq/page.tsx`, `apps/merchant/src/components/landing/Faq.tsx` (server component rendering `<details>` items from a `{ q, a }[]`), `apps/merchant/src/components/landing/PageFrame.tsx` (header/footer shell shared with `/` — extract from `page.tsx` in Task 2 if not already a component)
- Modify: `packages/i18n/locales/{ru,en,uz}/merchant.json` — new namespaces `faq` (12 entries) and `pages` (`telegram.*`, `api.*`, `faqPage.*` titles/descriptions/H1/answer/H2s)

**Interfaces:**

- Consumes: `alternates`, `ROBOTS`, `JsonLd`, `SEO_PATHS` (Task 3), `Faq` component (this task), strings.
- Produces: routes `/telegram`, `/api`, `/faq` in all locales (same slugs), each with `generateMetadata`, an H1, a first-paragraph direct answer, literal-question H2s, `FAQPage` + `BreadcrumbList` JSON-LD (`TechArticle` on `/api`).

- [ ] **Step 1: FAQ strings (ru; en 1:1; uz native)**

`faq.q1`…`faq.a12` in ru — the twelve pairs from the design doc §5.5 **with these edits**: a1 → `У оптового поставщика — например, у YuPay. После регистрации открывается каталог с оптовыми ценами. Разница между вашей закупкой и ценой, по которой вы продаёте подписчику, и есть ваш заработок.`; a8 (question «Можно ли посмотреть цены до регистрации?») → q8 `Когда я увижу цены?` / a8 `Сразу после регистрации: каталог с оптовыми ценами открывается бесплатно, без заявки и без разговора с менеджером.`; everything with «депозит» only as in a7 (`…списание возвращается на депозит автоматически…`); nothing about top-up. uz: q1–q4 from the doc §5.5 with the same edits (no `10–25 %`, `rozitsadan arzon` → `optom narxda`); q5–q12 written natively (register: `yechilgan pul oʻzi qaytadi`, `telefondan ishlaydi`, `shartnoma kerak emas`, `odatda 1–2 daqiqa`, `ID ni toʻlovdan oldin tekshiramiz`).

`pages.telegram`: `title` `Поставщик пополнений для Telegram-канала — YuPay`, `description` `Продаёте пополнения игр в своём Telegram-канале? Берите товар оптом: 20 брендов, заказ с телефона, ID игрока проверяем до оплаты, выдача за минуту. Без договора и минимального объёма.`, `h1` `Где брать товар для Telegram-канала с пополнениями`, `answer` (doc §4.3 paragraph, unchanged — it has no prices), H2s: `h2Instead` `Что вы получаете вместо ручной закупки`, `h2Day` `Первый день: от регистрации до первого заказа`, `h2WrongId` `Что делать, если подписчик дал неверный ID`, `h2Stuck` `Что делать, если заказ завис`, `h2Faq` `Частые вопросы админов каналов`, each with a 2–4-sentence body (`bodyInstead`, `bodyDay`, `bodyWrongId`, `bodyStuck`) written in the plan's register: instead = one cabinet with the whole catalog, a code in a minute, an order history you can search; day = register by email → confirm → the catalog opens → first order from the phone; wrongId = the check shows the nickname before anything is charged, «не смогли проверить» is shown as such; stuck = the status stays until the supplier's final answer; if delivery failed and the money came back, the charge returns to the deposit automatically; support is one tap away. The page's FAQ = q1, q2, q5, q6, q7, q9, q10, q12.

`pages.api`: `title` `API пополнения игр с автовыдачей — YuPay Оптом`, `description` `HTTP API для автоматического пополнения игр и сервисов: 6 эндпоинтов, HMAC-подпись, идемпотентность по вашему order_id, вебхуки, проверка ID игрока. Открытая спецификация OpenAPI 3.1.`, `h1` `API для автоматического пополнения игр и сервисов`, `answer` (doc §4.4 paragraph, unchanged), H2s exactly: `Есть ли сервис с API для автопополнения игр` · `Шесть эндпоинтов` (a table: method, path, purpose — from the answer paragraph) · `Идемпотентность: повтор запроса не списывает дважды` · `Вебхуки: как узнать, что товар выдан` · `Проверка ID игрока до заказа` · `Автоматический возврат при неудачной выдаче` · `Есть ли API для пополнения PUBG Mobile оптом` · `Как начать: ключ, подпись, первый заказ` (links to `/docs/quickstart`, `/docs/authentication`) — bodies reuse `landing.dev*Body` strings where they say the same thing (import them; do not duplicate text). FAQ = q3, q4, q10, q12. Add `<link rel="alternate" type="application/json" href="https://api.yupay.uz/merchant/openapi.json">` via `generateMetadata`'s `alternates.types`.

`pages.faqPage`: `title` `Оптовая закупка пополнений: вопросы — YuPay`, `description` `Ответы на вопросы об оптовой закупке пополнений игр: как это работает, что если ID неверный, нужен ли договор, есть ли API.`, `h1` `Вопросы об оптовой закупке, начистоту`. All twelve entries.

- [ ] **Step 2: Pages**

Each page: `export const revalidate = 3600`; `generateMetadata` (title/description/alternates/ROBOTS/openGraph); `<PageFrame locale>` (header + footer as on `/`); H1; the answer paragraph first; the H2 sections; `<Faq items>`; `<JsonLd>` with `BreadcrumbList` (Home → page) + `FAQPage` (the page's items) (+ `TechArticle` on `/api` with `headline: h1`, `about: "Game top-up API"`, `dateModified`). Cross-links: `/telegram` → `/faq`, `/register`, `#how` on `/`; `/api` → `/docs/*`, the OpenAPI URL, `/faq`; `/faq` → `/telegram`, `/api`, `/register`.

- [ ] **Step 3: Tests**

`apps/merchant/src/components/landing/Faq.test.tsx` is not possible (no RTL in this app? check `apps/merchant` devDependencies; `api.test.ts` exists — node-env). So: a unit test for the JSON-LD builder — create `apps/merchant/src/lib/jsonld.ts` with `faqPage(items: {q: string; a: string}[])`, `breadcrumbs(items: {name: string; url: string}[])`, `techArticle({headline, url, dateModified})`, and `apps/merchant/src/lib/jsonld.test.ts` asserting the `@type`s and that `faqPage` maps every item to `Question`/`acceptedAnswer`. Pages use these builders.

- [ ] **Step 4: Checks and commit**

Run: `pnpm --filter @yupay/merchant exec tsc --noEmit && pnpm --filter @yupay/merchant exec vitest run && pnpm --filter @yupay/merchant exec eslint src && pnpm --filter @yupay/i18n test && pnpm exec prettier --check apps/merchant/src packages/i18n/locales`. Then `rg -n "%|скидк|пополн(ить|ение) (баланс|депозит)" packages/i18n/locales/ru/merchant.json` — no hits in `landing`, `faq`, `pages`, `meta`.

```bash
git add apps/merchant/src packages/i18n/locales
git commit -m "feat(merchant/seo): /telegram, /api and /faq intent pages with FAQPage and breadcrumbs"
```

---

### Task 5: Docs, gate, and the owner's reminders

**Files:**

- Modify: `docs/architecture/module-map.md` (merchant app row: landing + intent pages + SEO layer), `apps/api/src/yupay/modules/merchants/README.md` (a short «Витрина программы» note pointing at the pages), `docs/runbooks/merchant-b2b.md` (new section «SEO/AEO: что смотреть» — the Loki query and the monthly 12-prompt panel from the design doc §8, verbatim), `docs/superpowers/specs/2026-09-17-reseller-seo-design.md` (a top note: «Owner rulings 2026-09-17: no top-up mentions, no discounts/percentages, no /prices; see the plan»)
- Create: `docs/decisions/0080-reseller-site-for-non-technical-resellers.md` (MADR: context = two audiences, the jargon on the manual path, the invisible site; decision = one landing for both intents with the admin first, developer below; server-rendered intent pages; SEO layer ported from the storefront; owner constraints; consequences = `/docs` untouched, `/prices` and blog series deferred, measurement panel)

- [ ] **Step 1: Write the docs** (each ≤ 1 page; the ADR follows `docs/decisions/0000-template.md`).

- [ ] **Step 2: Full gate**

Run: `make lint typecheck test && pnpm exec prettier --check .` Expected: green (the only pre-existing failures allowed are none — the alert/mypy/g2b fixes landed on 2026-09-17).

- [ ] **Step 3: Commit**

```bash
git add docs apps/api/src/yupay/modules/merchants/README.md
git commit -m "docs: reseller site for non-technical resellers (ADR-0080), SEO runbook section"
```

---

## Rollout (needs the owner's «пуш и деплой»)

1. Owner checks Cloudflare → zone `yupay.uz` → «Block AI Scrapers and Crawlers» is **off** and reseller.yupay.uz is not under Bot Fight Mode.
2. Push → Build images (`merchant` + `web`) → deploy. Verify: `https://reseller.yupay.uz/robots.txt` lists the AI crawlers; `/sitemap.xml` lists ru/uz/en × the SEO paths; `/llms.txt` 200; `/`, `/telegram`, `/api`, `/faq` render server-side (curl shows the H1 and the answer paragraph); `/cabinet` has `noindex`; `https://yupay.uz` footer links «Оптом / для перепродажи».
3. Owner (20 min): Bing Webmaster Tools (add host, sitemap), Yandex.Webmaster (region Tashkent), Google Search Console property; run the 12-prompt baseline panel from the runbook **before** announcing anything.
