# Steam «0% комиссии за сумы» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Профессионально подать УТП «пополнение Steam в Узбекистане за сумы — 0% комиссии»: фокусная секция на главной + highlight-чипы и SEO-контент на существующей `/store/steam`, без дубля страницы.

**Architecture:** Фронт-секция (RSC) на главной со ссылкой на `/store/steam`; переиспользуемое локализованное поле `highlights` в каталоге (бэк) рендерится чипами в hero brand-страницы; SEO-контент бренда `steam` — данные каталога (SQL/seed). Спека: `docs/superpowers/specs/2026-07-27-steam-zero-commission-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async) + Alembic + Pydantic v2 (api); Next.js 15 RSC + Tailwind v4 + next-intl (web); `@hey-api/openapi-ts` (api-client).

## Global Constraints

- **Правда 0%:** «0% = нет нашей комиссии сверху, 1:1» (клиент платит ровно то, что заходит на Steam; маржа в курсе). Не писать «0% на конвертацию» / «официальный курс Steam». «от 4%» — мок, правится на «0%».
- **SSG против старого API:** новое поле `highlights` на фронте — **опционально** (`highlights?: string[]`), в рендере `?? []` (memory `web-ssg-prerenders-against-deployed-api`). На бэке `BrandDetailOut.highlights` — default `[]`.
- **i18n:** любые новые user-facing строки — в `ru/en/uz` в одном PR. Деньги/суммы — `Intl.NumberFormat`/`formatUzs`, без конкатенации.
- **Money в minor units**, Decimal(py)/string(ts) — не трогаем логику оплаты (только подача/контент).
- **Coverage:** api ≥ 80%, web ≥ 70% (каталог — не 95%-зона).
- **RSC по умолчанию:** секция без `"use client"`, нулевой прирост клиентского JS.
- **Доки в том же PR:** ADR на поле каталога + module-map + реген openapi.

---

## File Structure

- `apps/api/src/yupay/modules/catalog/models.py` — колонка `highlights` на `BrandTranslation`.
- `apps/api/migrations/versions/0032_brand_highlights.py` — миграция (add nullable JSON).
- `apps/api/src/yupay/modules/catalog/schemas.py` — `BrandDetailOut.highlights`.
- `apps/api/src/yupay/modules/catalog/service.py` — `_pick_highlights` + проброс в detail.
- `apps/api/tests/integration/` — тест локализации `highlights`.
- `docs/decisions/0037-brand-highlights.md` — ADR.
- `packages/api-client/` + `docs/api/openapi.json` — реген (`make gen-api`).
- `apps/web/src/lib/catalog.ts` — `BrandDetail.highlights?: string[]`.
- `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx` — рендер highlight-чипов.
- `apps/web/src/components/sections/SteamZeroCommission.tsx` — секция главной.
- `apps/web/src/app/[locale]/page.tsx` — монтаж секции.
- `packages/i18n/locales/{ru,en,uz}/web.json` — namespace `steamZero` + правка `catalog.cards.steam.statCommission`.
- `apps/web/src/components/sections/SteamZeroCommission.test.tsx` — тест секции.
- `scripts/seed/steam_seo.sql` — SEO-контент бренда steam (highlights/desc/instructions/FAQ, 3 локали).

---

## Task 1: Backend `highlights` field on catalog brand translations

**Agent:** standard model (integration/schema judgment). Docs sub-steps included.

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/models.py` (imports + `BrandTranslation`)
- Create: `apps/api/migrations/versions/0032_brand_highlights.py`
- Modify: `apps/api/src/yupay/modules/catalog/schemas.py:156-173` (`BrandDetailOut`)
- Modify: `apps/api/src/yupay/modules/catalog/service.py` (add `_pick_highlights`, wire into `get_brand_by_slug`)
- Test: `apps/api/tests/integration/` (existing catalog brand-detail test module; add case)
- Docs: `docs/decisions/0037-brand-highlights.md`, `docs/architecture/module-map.md`

**Interfaces:**

- Produces: `BrandDetailOut.highlights: list[str]` (default `[]`), localized like `description` with `DEFAULT_LOCALE` fallback. Consumed by Task 2 (frontend) and Task 4 (seed data).

- [ ] **Step 1: Write the failing test**

Add to the catalog brand-detail integration test module. Seed a brand with two translations (locale `ru` with highlights, `en` without), then assert localization + fallback + default-empty:

```python
async def test_brand_detail_returns_localized_highlights(db_session):
    brand = await _seed_brand_with_translations(
        db_session,
        slug="steamtest",
        translations={
            "ru": {"name": "Steam", "highlights": ["0% комиссии", "Оплата в сумах"]},
            "en": {"name": "Steam", "highlights": None},
        },
    )
    ru = await get_brand_by_slug(db_session, "steamtest", locale="ru")
    assert ru is not None
    assert ru.highlights == ["0% комиссии", "Оплата в сумах"]

    # en has no highlights -> falls back to DEFAULT_LOCALE (ru) row
    en = await get_brand_by_slug(db_session, "steamtest", locale="en")
    assert en is not None
    assert en.highlights == ["0% комиссии", "Оплата в сумах"]


async def test_brand_detail_highlights_default_empty(db_session):
    await _seed_brand_with_translations(
        db_session, slug="plainbrand",
        translations={"ru": {"name": "Plain", "highlights": None}},
    )
    got = await get_brand_by_slug(db_session, "plainbrand", locale="ru")
    assert got is not None
    assert got.highlights == []
```

> If the module lacks a `_seed_brand_with_translations` helper, mirror the existing brand-seeding fixture and add `highlights` to the `BrandTranslation(...)` kwargs.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration -k "highlights" -v`
Expected: FAIL — `BrandTranslation` has no `highlights` / `BrandDetailOut` has no attribute `highlights`.

- [ ] **Step 3: Add the model column**

In `apps/api/src/yupay/modules/catalog/models.py`, add `JSON` to the `from sqlalchemy import (...)` block, then add to `BrandTranslation` (after `instructions`):

```python
    # Short localized value-prop chips shown on the brand hero (e.g. Steam's
    # "0% комиссии", "Оплата в сумах"). NULL/absent -> no chips rendered.
    highlights: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: Create the migration**

`apps/api/migrations/versions/0032_brand_highlights.py`:

```python
"""Add ``brand_translations.highlights`` (localized value-prop chips).

Nullable JSON list of short strings rendered on the brand hero. Additive and
nullable, so existing rows are untouched.

Revision ID: 0032_brand_highlights
Revises: 0031_uzum_amount_sum_to_tiyin
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_brand_highlights"
down_revision: str | None = "0031_uzum_amount_sum_to_tiyin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brand_translations",
        sa.Column("highlights", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brand_translations", "highlights")
```

- [ ] **Step 5: Add the schema field**

In `apps/api/src/yupay/modules/catalog/schemas.py`, `BrandDetailOut`, after `faqs`:

```python
    highlights: list[str] = Field(default_factory=list)
```

- [ ] **Step 6: Add the service picker and wire it in**

In `apps/api/src/yupay/modules/catalog/service.py`, add near `_pick_translation`:

```python
def _pick_highlights(
    translations: list[Any],
    locale: str,
    *,
    fallback: str = DEFAULT_LOCALE,
) -> list[str]:
    """Return the localized ``highlights`` list for the brand, or ``[]``.

    Only brand translations carry ``highlights``; read defensively via
    ``getattr`` and coerce NULL to an empty list.
    """
    by_locale = {t.locale: t for t in translations}
    chosen = (
        by_locale.get(locale)
        or by_locale.get(fallback)
        or (translations[0] if translations else None)
    )
    if chosen is None:
        return []
    return list(getattr(chosen, "highlights", None) or [])
```

In `get_brand_by_slug`, after the `name, short_desc, description, instructions = _pick_translation(...)` line:

```python
    highlights = _pick_highlights(brand.translations, locale)
```

and add to the `BrandDetailOut(...)` constructor (after `faqs=faqs_out,`):

```python
        highlights=highlights,
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration -k "highlights" -v`
Expected: PASS (both cases).

- [ ] **Step 8: Regression + lint + type**

Run: `cd apps/api && uv run pytest tests/integration -k "catalog or brand" -q && uv run ruff check src/yupay/modules/catalog && uv run mypy src/yupay/modules/catalog`
Expected: green; no new N+1 (highlights read from already-loaded `translations`).

- [ ] **Step 9: Docs — ADR + module-map**

Create `docs/decisions/0037-brand-highlights.md` (MADR template `docs/decisions/0000-template.md`): decision = add a nullable localized `highlights` JSON list to `BrandTranslation` (reusable across brands; not per-slug hardcode; NULL → no chips). Update `docs/architecture/module-map.md` catalog entry to mention `highlights` on the brand-detail contract.

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/yupay/modules/catalog apps/api/migrations/versions/0032_brand_highlights.py apps/api/tests docs/decisions/0037-brand-highlights.md docs/architecture/module-map.md
git commit -m "feat(api/catalog): localized brand highlights chips on brand detail"
```

---

## Task 2: Regenerate API client + render highlight chips on `/store/steam`

**Agent:** standard model.

**Files:**

- Regenerate: `docs/api/openapi.json`, `packages/api-client/` (`make gen-api`)
- Modify: `apps/web/src/lib/catalog.ts:93-100` (`BrandDetail`)
- Modify: `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx` (hero chip row + `Chip` accent variant)
- Test: `apps/web/src/app/[locale]/store/[brandSlug]/` — brand-page render test (or a focused `Chip`-row unit test)

**Interfaces:**

- Consumes: `BrandDetailOut.highlights` (Task 1).
- Produces: highlight chips visible in the brand hero when non-empty.

- [ ] **Step 1: Regenerate the API client**

Run: `make gen-api`
Expected: `docs/api/openapi.json` and `packages/api-client/` show `highlights` on the brand-detail type; no other drift.

- [ ] **Step 2: Add the optional field to the web DTO**

In `apps/web/src/lib/catalog.ts`, `BrandDetail`, add (keep it **optional** — SSG prerenders against the old API):

```ts
  // Optional: an older deployed API (or a build prerendering against one) may
  // omit this, so consumers must tolerate `undefined` and default to `[]`.
  highlights?: string[];
```

- [ ] **Step 3: Write the failing render test**

Create a test that renders the brand page hero (or extract a `HighlightChips` piece) asserting chips appear for a brand with `highlights` and are absent otherwise. Minimal approach — a small presentational helper `HighlightChips({ items }: { items: string[] })` in the page file’s module, tested directly:

```tsx
import { render, screen } from "@testing-library/react";
import { HighlightChips } from "./page";

test("renders a chip per highlight", () => {
  render(<HighlightChips items={["0% комиссии", "Оплата в сумах"]} />);
  expect(screen.getByText("0% комиссии")).toBeInTheDocument();
  expect(screen.getByText("Оплата в сумах")).toBeInTheDocument();
});

test("renders nothing when empty", () => {
  const { container } = render(<HighlightChips items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/app/[locale]/store/[brandSlug] -t "highlight"`
Expected: FAIL — `HighlightChips` not exported.

- [ ] **Step 5: Implement `HighlightChips` and render it**

In `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx`, export a small helper and render it in the hero chip row. Add `Check` to the lucide import.

```tsx
export function HighlightChips({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      {items.map((h) => (
        <span
          key={h}
          className="border-primary/40 bg-primary/10 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur"
        >
          <Check size={13} className="text-primary shrink-0" />
          {h}
        </span>
      ))}
    </>
  );
}
```

In `BrandPage`, compute `const highlights = brand.highlights ?? [];` and render inside the existing chip row (after the `securityChip`, before `maintenance`):

```tsx
<HighlightChips items={highlights} />
```

- [ ] **Step 6: Run the test + typecheck**

Run: `cd apps/web && pnpm vitest run src/app/[locale]/store/[brandSlug] -t "highlight" && pnpm exec tsc --noEmit`
Expected: PASS; no type errors (`highlights?` handled via `?? []`).

- [ ] **Step 7: Commit**

```bash
git add packages/api-client docs/api/openapi.json apps/web/src/lib/catalog.ts "apps/web/src/app/[locale]/store/[brandSlug]/page.tsx" "apps/web/src/app/[locale]/store/[brandSlug]"/*.test.tsx
git commit -m "feat(web/store): render localized brand highlight chips on brand hero"
```

---

## Task 3: Homepage `SteamZeroCommission` section (+ fix «от 4%» → «0%»)

**Agent:** UI-agent (ui-design:ui-designer) for the visual; standard reviewer. Design-system tokens only.

**Files:**

- Create: `apps/web/src/components/sections/SteamZeroCommission.tsx`
- Create: `apps/web/src/components/sections/SteamZeroCommission.test.tsx`
- Modify: `apps/web/src/app/[locale]/page.tsx` (import + mount after `TrustBand`)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (`steamZero` namespace + `catalog.cards.steam.statCommission`)

**Interfaces:**

- Consumes: static i18n `web.steamZero.*`; asset `public/brands/steam-mono.png`, `steam-bg.jpg`, `public/payment/{click,payme,uzum,usdt}.png`. No API dependency (independent of Tasks 1–2).

- [ ] **Step 1: Add i18n keys (all three locales)**

Add a `steamZero` block to each `web.json`. **RU** (`packages/i18n/locales/ru/web.json`):

```json
"steamZero": {
  "eyebrow": "Steam · Узбекистан",
  "title": "0% комиссии на пополнение Steam",
  "subtitle": "Оплата в сумах через Click, Payme и Uzum. Сколько платите — столько заходит на баланс Steam. Без скрытых сборов.",
  "payLabel": "Оплата в сумах",
  "chipSpeed": "1–3 минуты",
  "chipNoPassword": "Без пароля",
  "chipGuarantee": "Гарантия возврата",
  "cta": "Пополнить Steam",
  "logoAlt": "Steam"
}
```

**EN** (`.../en/web.json`):

```json
"steamZero": {
  "eyebrow": "Steam · Uzbekistan",
  "title": "0% fee on Steam top-ups",
  "subtitle": "Pay in so‘m via Click, Payme and Uzum. What you pay is what lands on your Steam balance — no hidden fees.",
  "payLabel": "Pay in so‘m",
  "chipSpeed": "1–3 minutes",
  "chipNoPassword": "No password",
  "chipGuarantee": "Money-back guarantee",
  "cta": "Top up Steam",
  "logoAlt": "Steam"
}
```

**UZ** (`.../uz/web.json`):

```json
"steamZero": {
  "eyebrow": "Steam · Oʻzbekiston",
  "title": "Steam hisobini 0% komissiya bilan toʻldiring",
  "subtitle": "Click, Payme va Uzum orqali soʻmda toʻlang. Qancha toʻlasangiz, Steam hisobiga shuncha tushadi — yashirin toʻlovlarsiz.",
  "payLabel": "Soʻmda toʻlov",
  "chipSpeed": "1–3 daqiqa",
  "chipNoPassword": "Parolsiz",
  "chipGuarantee": "Pul qaytarish kafolati",
  "cta": "Steamni toʻldirish",
  "logoAlt": "Steam"
}
```

Also fix the mock commission stat in each locale — `catalog.cards.steam.statCommission`: RU `"от 4%"`→`"0%"`, EN `"from 4%"`→`"0%"`, UZ `"4% dan"`→`"0%"`.

- [ ] **Step 2: Write the failing section test**

`apps/web/src/components/sections/SteamZeroCommission.test.tsx`. Mock `next-intl/server` `getTranslations` to return keys verbatim, render the (async) component, assert title, CTA href to `/ru/store/steam`, and the four payment icons:

```tsx
import { render, screen } from "@testing-library/react";
import { SteamZeroCommission } from "./SteamZeroCommission";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (k: string) => `steamZero.${k}`,
}));

test("renders heading, CTA to /store/steam and payment icons", async () => {
  render(await SteamZeroCommission({ locale: "ru" }));
  expect(screen.getByRole("heading", { name: /steamZero\.title/ })).toBeInTheDocument();
  const cta = screen.getByRole("link", { name: /steamZero\.cta/ });
  expect(cta).toHaveAttribute("href", "/ru/store/steam");
  for (const p of ["Click", "Payme", "Uzum", "USDT"]) {
    expect(screen.getByAltText(p)).toBeInTheDocument();
  }
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/components/sections/SteamZeroCommission.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the section**

`apps/web/src/components/sections/SteamZeroCommission.tsx` (RSC, no `"use client"`). Design-system tokens only; Steam mono logo inverted to white on the dark ground; Steam bg with darkening gradient; lime CTA via `buttonStyles`.

```tsx
import { ArrowRight, RotateCcw, ShieldCheck, Zap } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonStyles } from "@/lib/button";

const PAYMENTS = [
  { src: "/payment/click.png", alt: "Click" },
  { src: "/payment/payme.png", alt: "Payme" },
  { src: "/payment/uzum.png", alt: "Uzum" },
  { src: "/payment/usdt.png", alt: "USDT" },
] as const;

/**
 * Steam "0% commission, pay in so‘m" value band — the storefront's sharpest USP
 * for the Uzbek market. Type-led claim + payment rail + trust chips + a single
 * CTA into the real product page (/store/steam). RSC, zero client JS.
 */
export async function SteamZeroCommission({ locale }: { locale: string }) {
  const t = await getTranslations("web.steamZero");
  const chips = [
    { Icon: Zap, label: t("chipSpeed") },
    { Icon: ShieldCheck, label: t("chipNoPassword") },
    { Icon: RotateCcw, label: t("chipGuarantee") },
  ] as const;

  return (
    <section className="relative overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <Image
          src="/brands/steam-bg.jpg"
          alt=""
          fill
          sizes="100vw"
          className="object-cover object-center opacity-40"
        />
        <div className="absolute inset-0 bg-[radial-gradient(120%_120%_at_50%_0%,rgba(10,13,26,0.75)_0%,rgba(10,13,26,0.94)_60%,#0A0D1A_100%)]" />
        <div
          className="glow-lime absolute"
          style={{
            width: 560,
            height: 560,
            left: "50%",
            top: "10%",
            transform: "translate(-50%,-50%)",
          }}
        />
      </div>

      <div className="mx-auto max-w-[1100px] px-6 py-20 sm:px-10 sm:py-28">
        <div className="flex flex-col items-center text-center">
          <span className="relative mb-6 grid h-16 w-16 place-items-center rounded-2xl border border-white/15 bg-white/5 backdrop-blur">
            <Image
              src="/brands/steam-mono.png"
              alt={t("logoAlt")}
              width={44}
              height={44}
              className="invert"
            />
          </span>

          <div className="text-primary mb-3 font-mono text-[12px] font-semibold uppercase tracking-[0.14em]">
            {t("eyebrow")}
          </div>
          <h2 className="font-display max-w-[15ch] text-balance text-[clamp(2rem,5vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.03em] text-white">
            {t("title")}
          </h2>
          <p className="text-tx-mute mt-5 max-w-[54ch] text-[15px] leading-relaxed sm:text-base">
            {t("subtitle")}
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
            {chips.map(({ Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-black/40 px-3.5 py-2 text-[13px] font-semibold text-white backdrop-blur"
              >
                <Icon size={14} className="text-primary shrink-0" />
                {label}
              </span>
            ))}
          </div>

          <div className="mt-8 flex flex-col items-center gap-3">
            <span className="text-tx-dim font-mono text-[11px] uppercase tracking-[0.12em]">
              {t("payLabel")}
            </span>
            <div className="flex items-center gap-2.5">
              {PAYMENTS.map((p) => (
                <span
                  key={p.alt}
                  className="grid h-10 w-14 place-items-center rounded-lg border border-white/10 bg-white/95 px-2"
                >
                  <Image
                    src={p.src}
                    alt={p.alt}
                    width={40}
                    height={20}
                    className="h-5 w-auto object-contain"
                  />
                </span>
              ))}
            </div>
          </div>

          <Link
            href={`/${locale}/store/steam`}
            className={buttonStyles({ size: "lg", className: "mt-10" })}
          >
            {t("cta")}
            <ArrowRight size={18} />
          </Link>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/web && pnpm vitest run src/components/sections/SteamZeroCommission.test.tsx`
Expected: PASS.

- [ ] **Step 6: Mount on the homepage**

In `apps/web/src/app/[locale]/page.tsx`: add `import { SteamZeroCommission } from "@/components/sections/SteamZeroCommission";` and render it after `<TrustBand />`, before `<CatalogBento .../>`:

```tsx
      <TrustBand />
      <SteamZeroCommission locale={locale} />
      <CatalogBento locale={locale} />
```

- [ ] **Step 7: Lint + typecheck + i18n parity**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm eslint src/components/sections/SteamZeroCommission.tsx` then from repo root the i18n key-parity check (`make lint` or the i18n check script) to confirm ru/en/uz all have `steamZero.*`.
Expected: green; no missing-locale-key failures.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/sections/SteamZeroCommission.tsx apps/web/src/components/sections/SteamZeroCommission.test.tsx "apps/web/src/app/[locale]/page.tsx" packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json
git commit -m "feat(web/home): Steam 0%-commission section + fix mock commission stat"
```

---

## Task 4: SEO content pack for the `steam` brand (data, 3 locales)

**Agent:** SEO-agent (copywriting) for the localized copy; standard reviewer for SQL correctness. **No app code.**

**Files:**

- Create: `scripts/seed/steam_seo.sql` — idempotent UPDATE/UPSERT of `brand_translations` (`highlights`, `short_description`, `description`, `instructions`) + `brand_faqs`(+translations) for brand `steam`, all three locales.
- Modify: `docs/api/README.md` — note that `highlights` is content-managed (SQL/seed), not seeded by fixtures.

**Interfaces:**

- Consumes: `highlights` column (Task 1). Applied to prod by the user via `!`/psql — **not** an Alembic data migration.

- [ ] **Step 1: Draft the localized copy (SEO agent)**

Produce, per locale (ru/en/uz), grounded strictly in the 0%-truth (no "official Steam rate", no invented commission):

- `highlights` (3–4 short chips): RU `["0% комиссии", "Оплата в сумах", "1–3 минуты", "Без пароля"]` (+ en/uz equivalents).
- `short_description` (≤512 chars), `description` (long, keyword «пополнение Steam Узбекистан за сумы 0%» naturally, no stuffing), `instructions` (how-to + supported regions + where to find your ID).
- 4 FAQ Q/A: комиссия? / оплата в сумах? / за сколько зачислится? / нужен ли пароль?

- [ ] **Step 2: Write the idempotent seed SQL**

`scripts/seed/steam_seo.sql` — `UPDATE brand_translations SET highlights = ..., short_description = ..., description = ..., instructions = ... WHERE brand_id = (SELECT id FROM brands WHERE slug='steam') AND locale='ru';` (repeat en/uz). For FAQs use upsert keyed on `(brand_id, sort_order)` or delete-then-insert within a transaction. `highlights` written as JSON, e.g. `'["0% комиссии","Оплата в сумах","1–3 минуты","Без пароля"]'::json`.

- [ ] **Step 3: Dry-run against a local DB**

Run: `make dev` (or a local psql) → `psql ... -f scripts/seed/steam_seo.sql` in a transaction with `ROLLBACK` first, then re-run to confirm idempotency (second run changes nothing / same result).
Expected: brand `steam` rows updated; running twice is a no-op.

- [ ] **Step 4: Verify on the running web app**

Load `/{ru,en,uz}/store/steam` locally: highlight chips render, About/Instructions/FAQ show the new copy, FAQ appears in `FAQPage` JSON-LD (view source), meta `<title>`/`description` reflect the new brand description.
Expected: all three locales correct; homepage `SteamZeroCommission` CTA lands here.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed/steam_seo.sql docs/api/README.md
git commit -m "feat(seed/steam): SEO content + highlights for the steam brand (ru/en/uz)"
```

> **Prod application is user-gated:** the SQL is applied to prod by the user (per the standing deploy rule), not by CI. Homepage/section code (Tasks 1–3) deploys via the normal pipeline; the content lands when the user runs the seed.

---

## Self-Review

- **Spec coverage:** Слой A → Task 3; Слой B → Task 1 (бэк) + Task 2 (фронт); Слой C → Task 4 + card-stat fix in Task 3; Слой D (опц. отзывы) → deferred/optional, not blocking (noted out-of-scope-ish). ✅
- **Placeholder scan:** all steps carry real code/commands. FAQ/description longform copy is produced by the SEO agent in Task 4 Step 1 (content, not code) — acceptable. ✅
- **Type consistency:** `highlights` — `list[str]` (py, default `[]`) ↔ `highlights?: string[]` (ts, `?? []`); `_pick_highlights` returns `list[str]`; `HighlightChips({items:string[]})`. Names match across tasks. ✅
- **SSG constraint** honored (optional field). **i18n parity** enforced in Task 3 Step 7. **Docs** (ADR/module-map/openapi/api README) included. ✅
