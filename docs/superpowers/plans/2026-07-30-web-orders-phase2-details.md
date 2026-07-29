# Web Orders — Phase 2 (Order-details rework + provider + money) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WEB order-details page show what the customer actually needs — the amount they paid (valid currency formatting), the payment provider (logo/text), the items, the dates, real per-status content (incl. "выполняется"), and a clean, translated reveal of the delivered artifact — with Mini App parity for the payment provider.

**Architecture:** Backend adds `payment_provider` to `OrderOut` (the newest succeeded payment's provider, normalized, loaded without N+1 via a `selectinload(Order.payments)`). A shared money formatter is made currency-aware (UZS zero-decimal, USDT). The web `OrderStatus.tsx` is decomposed into focused sub-components under `apps/web/src/components/order/` (`OrderSummary`, `OrderItems`, `StatusBlock`, and the existing artifact reveal), each translated. The Mini App gains a provider line. All new copy lands in ru/en/uz.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Pydantic v2; Next.js 15 web (next-intl, TanStack Query); Vite miniapp; `@yupay/utils` money helper; Vitest (TS unit) + Playwright (controller visual verification).

## Global Constraints

- Never send supplier/internal identifiers to any frontend (Phase 1 guarantee stays; this phase adds NO new leak — `payment_provider` is a safe slug like `click`/`payme`/`uzum`/`octo`/`wallet`).
- Money: full-unit `Decimal` in DB; format per currency — **USD/USDT 2-dec (`$10.00`), UZS zero-decimal with grouping, RUB per-locale**; never raw, never string-concat a bare number.
- Provider slug normalization: `click_miniapp` → `click` (same brand). Known brands render their proper name (Click/Payme/Uzum/Octo) + logo where available; `wallet` renders a localized "paid from balance" label; unknown slugs render the slug as text.
- i18n: every new user-facing string added to `packages/i18n/locales/{ru,en,uz}/web.json` (web, nested) and, for the miniapp provider line, `packages/i18n/locales/{ru,en,uz}/miniapp.json` (flat dotted, RU canonical) — in the SAME task.
- No N+1: the orders LIST endpoint must not issue a per-order payment query — verify the loaded-options approach batches (one `selectinload`).
- `mypy apps` (from repo root) 0 errors; ruff clean; `tsc --noEmit` clean for web + miniapp. Do NOT run a host `next build` for web (bind-mount `.next` trap). OpenAPI regenerated (`make gen-api`), no drift.
- Web component file soft limit 300 LOC — decompose `OrderStatus.tsx` rather than growing it.
- Provider values that exist: `click`, `click_miniapp`, `payme`, `uzum`, `octo`, `wallet`, `mock` (dev). Logos present under `apps/web/public/payment/`: `click.svg`, `payme.png`, `uzum.png` (no octo/wallet/mock logo → text).

---

### Task 1: Backend — `payment_provider` on `OrderOut`

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/models.py` (add `payments` relationship on `Order`)
- Modify: `apps/api/src/yupay/modules/orders/service.py:57-69` (`_order_load_options` — add `selectinload(Order.payments)`) + add `succeeded_provider_for(order)` helper
- Modify: `apps/api/src/yupay/modules/orders/schemas.py:97-115` (`OrderOut` — add `payment_provider: str | None = None`)
- Modify: `apps/api/src/yupay/modules/orders/routes.py:41-50` (`_to_order_out` / `_to_admin_order_out` — set `payment_provider`)
- Regenerate: `docs/api/openapi.json` (`make gen-api`)
- Test: `apps/api/tests/integration/test_orders_routes.py` (assert `payment_provider` on a paid order + query-count guard on list)

**Interfaces:**

- Consumes: `Payment` model (`payments/models.py` — `order_id`, `provider`, `status`, `succeeded_at`).
- Produces: `OrderOut.payment_provider: str | None`; `Order.payments` relationship; `succeeded_provider_for(order: Order) -> str | None` (newest succeeded payment's provider, `click_miniapp`→`click`, else `None`).

- [ ] **Step 1: Write the failing integration assertion**

In `apps/api/tests/integration/test_orders_routes.py`, in the test that drives an order to `paid`/`delivered` (or add near `test_admin_can_list_and_cancel`), after paying via the existing flow assert the customer order carries the provider:

```python
    order_resp = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert order_resp.status_code == 200, order_resp.text
    body = order_resp.json()
    # The provider the customer actually paid with is surfaced (safe slug).
    assert body["payment_provider"] in {"click", "payme", "uzum", "octo", "wallet", "mock"}
```

(Use the same token/order the surrounding test already pays. If that test pays via `mock`, assert `== "mock"`.)

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_routes.py -k "provider or list_and_cancel" -v`
Expected: FAIL — `payment_provider` key absent (KeyError / None not in set).

- [ ] **Step 3: Add the `Order.payments` relationship**

In `apps/api/src/yupay/modules/orders/models.py`, add to the `Order` model (mirror the existing `items` relationship style; do NOT add a back-populates that would force a payments-model import cycle — a one-directional relationship keyed on `Payment.order_id` is enough):

```python
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        primaryjoin="Order.id == foreign(Payment.order_id)",
        viewonly=True,
        lazy="raise",  # only ever loaded explicitly via selectinload; never lazy on the request path
    )
```

Add the `TYPE_CHECKING` import for `Payment` if needed (`from yupay.modules.payments.models import Payment`). `viewonly=True` because orders never mutate payments; `lazy="raise"` guards against an accidental N+1 (a read path that forgot the selectinload will error loudly in tests, not silently fan out).

- [ ] **Step 4: Load it without N+1 + add the provider helper**

In `apps/api/src/yupay/modules/orders/service.py`, add `selectinload(Order.payments)` to `_order_load_options()` (alongside the existing item/sku/product/brand chain), and add:

```python
def succeeded_provider_for(order: Order) -> str | None:
    """The provider of the order's newest succeeded payment, normalized.

    ``click_miniapp`` collapses to ``click`` (same brand). Returns ``None``
    when nothing has succeeded yet (e.g. pending_payment). Reads the
    eager-loaded ``order.payments`` collection — never triggers a query.
    """
    succeeded = [p for p in order.payments if p.status == "succeeded"]
    if not succeeded:
        return None
    latest = max(succeeded, key=lambda p: p.succeeded_at or p.created_at)
    provider = latest.provider
    return "click" if provider == "click_miniapp" else provider
```

- [ ] **Step 5: Add the schema field + set it in assembly**

In `apps/api/src/yupay/modules/orders/schemas.py`, add to `OrderOut` (after `currency`/totals block):

```python
    payment_provider: str | None = None
```

In `apps/api/src/yupay/modules/orders/routes.py`, set it in both assemblers (import `succeeded_provider_for` from the service):

```python
def _to_order_out(order: Order, locale: str = "ru") -> OrderOut:
    out = OrderOut.model_validate(order)
    out.payment_provider = succeeded_provider_for(order)
    _attach_displays(out, order, locale)
    return out


def _to_admin_order_out(order: Order, locale: str = "ru") -> OrderAdminOut:
    out = OrderAdminOut.model_validate(order)
    out.payment_provider = succeeded_provider_for(order)
    _attach_displays(out, order, locale)
    return out
```

(Keep whatever `_attach_displays` call already exists; only add the `payment_provider` line. If `_to_admin_order_out` currently does `OrderAdminOut.model_validate(order)` without `_attach_displays`, leave that as-is and just add the provider line.)

- [ ] **Step 6: Run the API test to green**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_routes.py -k "provider or list_and_cancel" -v`
Expected: PASS.

- [ ] **Step 7: Guard the list endpoint against N+1**

In the same test file, in the list test, wrap the `GET /api/v1/orders` call in the project's existing query-counter (search the tests for `assert_query_count` / `count_queries` / an `echo`-based counter used by other list tests — reuse that exact helper). Assert the query count does not scale with the number of orders (constant within a small bound). If no such helper exists in the suite, instead assert that fetching a list of ≥2 paid orders returns `payment_provider` on each without error (the `lazy="raise"` guard already converts any missed eager-load into a test failure).

Run: `cd apps/api && uv run pytest tests/integration/test_orders_routes.py -v`
Expected: PASS (all order route tests).

- [ ] **Step 8: Regenerate OpenAPI + lint/type**

Run: `make gen-api` then `cd apps/api && uv run ruff check src tests && uv run ruff format --check src` and (repo root) `uv run mypy apps`.
Verify `docs/api/openapi.json` `OrderOut` now has `payment_provider`. Expected: clean, no unexpected drift.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/yupay/modules/orders/ apps/api/tests/integration/test_orders_routes.py docs/api/openapi.json
git commit -m "feat(api/orders): expose payment_provider on OrderOut

The provider of the order's newest succeeded payment (click_miniapp
normalized to click) is surfaced on the customer OrderOut, eager-loaded via
selectinload(Order.payments) to avoid N+1. None until a payment succeeds.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Shared money formatter — currency-aware decimals

**Files:**

- Modify: `packages/utils/src/money.ts` (`formatMoney` — zero-decimal currencies + USDT)
- Test: `packages/utils/src/money.test.ts` (create or extend)

**Interfaces:**

- Produces: `formatMoney(amount: string, currency: string, locale?: string): string` — unchanged signature; correct decimals per currency.

- [ ] **Step 1: Write failing tests**

Create/extend `packages/utils/src/money.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("formats USD with two decimals", () => {
    expect(formatMoney("10", "USD", "en-US")).toBe("$10.00");
  });
  it("formats UZS with zero decimals and grouping", () => {
    // en-US grouping keeps it locale-stable for the assertion
    const out = formatMoney("20000", "UZS", "en-US");
    expect(out).not.toMatch(/\.\d/); // no fractional part
    expect(out).toMatch(/20[,\s]?000/);
  });
  it("formats USDT as a plain amount with the ticker (not a real ISO currency)", () => {
    expect(formatMoney("12.5", "USDT", "en-US")).toBe("12.5 USDT");
  });
  it("falls back gracefully for an unknown currency", () => {
    expect(formatMoney("5", "ZZZ", "en-US")).toMatch(/5(\.00)? ZZZ/);
  });
});
```

- [ ] **Step 2: Run and watch fail**

Run: `pnpm --filter @yupay/utils exec vitest run src/money.test.ts`
Expected: FAIL (USDT throws inside Intl today → catch gives `12.50 USDT` not `12.5 USDT`; UZS shows 2 decimals).

- [ ] **Step 3: Implement currency-aware formatting**

Replace the body of `packages/utils/src/money.ts` `formatMoney`:

```typescript
/** ISO 4217 currencies YuPay handles that carry no minor unit. */
const ZERO_DECIMAL_CURRENCIES = new Set(["UZS"]);

/**
 * Format a full-unit decimal amount for display.
 *
 * - USD / RUB and other 2-dp ISO currencies → locale currency style, 2 dp.
 * - UZS → zero decimals with grouping.
 * - USDT is not a real ISO 4217 code, so Intl currency style throws; render
 *   it as a plain grouped number with the "USDT" ticker appended.
 */
export function formatMoney(amount: string, currency: string, locale = "ru-RU"): string {
  const num = Number.parseFloat(amount);
  const safe = Number.isFinite(num) ? num : 0;
  const fractionDigits = ZERO_DECIMAL_CURRENCIES.has(currency) ? 0 : 2;

  if (currency === "USDT") {
    const n = safe.toLocaleString(locale, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    });
    return `${n} USDT`;
  }

  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(safe);
  } catch {
    return `${safe.toFixed(fractionDigits)} ${currency}`;
  }
}
```

- [ ] **Step 4: Run tests to green**

Run: `pnpm --filter @yupay/utils exec vitest run src/money.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

Run: `pnpm --filter @yupay/utils exec tsc --noEmit`

```bash
git add packages/utils/src/money.ts packages/utils/src/money.test.ts
git commit -m "feat(utils/money): currency-aware decimals (UZS zero-dec, USDT ticker)

formatMoney now renders UZS with no minor unit, USDT as a plain grouped
amount + ticker (not a real ISO code), and USD/RUB per-locale with 2 dp.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Web — payment-provider display map + order type

**Files:**

- Create: `apps/web/src/lib/payment-providers.ts`
- Modify: `apps/web/src/lib/orders-types.ts` (add `payment_provider: string | null` to `OrderOut`)
- Create: `apps/web/src/components/order/PaymentProviderBadge.tsx`
- Test: `apps/web/src/lib/payment-providers.test.ts`

**Interfaces:**

- Produces:
  - `paymentProviderDisplay(provider: string | null): { name?: string; nameKey?: string; logo?: string } | null`
  - `<PaymentProviderBadge provider={order.payment_provider} />` — renders logo+name or localized wallet label; renders nothing for `null`.

- [ ] **Step 1: Add the type field**

In `apps/web/src/lib/orders-types.ts`, add to `OrderOut` (near `currency`/totals):

```typescript
payment_provider: string | null;
```

- [ ] **Step 2: Write the failing map test**

Create `apps/web/src/lib/payment-providers.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { paymentProviderDisplay } from "./payment-providers";

describe("paymentProviderDisplay", () => {
  it("maps click (and click_miniapp) to the Click brand + logo", () => {
    expect(paymentProviderDisplay("click")).toEqual({ name: "Click", logo: "/payment/click.svg" });
    expect(paymentProviderDisplay("click_miniapp")).toEqual({
      name: "Click",
      logo: "/payment/click.svg",
    });
  });
  it("maps payme and uzum to their logos", () => {
    expect(paymentProviderDisplay("payme")).toEqual({ name: "Payme", logo: "/payment/payme.png" });
    expect(paymentProviderDisplay("uzum")).toEqual({ name: "Uzum", logo: "/payment/uzum.png" });
  });
  it("maps octo to a text badge (no logo asset)", () => {
    expect(paymentProviderDisplay("octo")).toEqual({ name: "Octo" });
  });
  it("maps wallet to a localizable label key", () => {
    expect(paymentProviderDisplay("wallet")).toEqual({ nameKey: "paidWithWallet" });
  });
  it("renders an unknown slug as plain text and null as null", () => {
    expect(paymentProviderDisplay("mock")).toEqual({ name: "mock" });
    expect(paymentProviderDisplay(null)).toBeNull();
  });
});
```

- [ ] **Step 2b: Run and watch fail**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/payment-providers.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the map**

Create `apps/web/src/lib/payment-providers.ts`:

```typescript
export interface ProviderDisplay {
  /** A proper brand name rendered as-is (Click, Payme, …) or an unknown slug. */
  name?: string;
  /** An i18n key under the `orders` namespace for a localized label (wallet). */
  nameKey?: string;
  /** Public path to a logo asset, when one exists. */
  logo?: string;
}

/**
 * Map a payment-provider slug to how the customer should see it on an order.
 * Backend already normalizes `click_miniapp` → `click`; we tolerate both.
 * Returns null when there is no provider yet (unpaid order).
 */
export function paymentProviderDisplay(provider: string | null): ProviderDisplay | null {
  switch (provider) {
    case "click":
    case "click_miniapp":
      return { name: "Click", logo: "/payment/click.svg" };
    case "payme":
      return { name: "Payme", logo: "/payment/payme.png" };
    case "uzum":
      return { name: "Uzum", logo: "/payment/uzum.png" };
    case "octo":
      return { name: "Octo" };
    case "wallet":
      return { nameKey: "paidWithWallet" };
    case null:
    case "":
      return null;
    default:
      return { name: provider };
  }
}
```

- [ ] **Step 4: Build the badge component**

Create `apps/web/src/components/order/PaymentProviderBadge.tsx` (Server Component-safe; uses next-intl `useTranslations`, so it is a client component only if the parent is — keep it a plain component that receives `t`):

```tsx
"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import { paymentProviderDisplay } from "@/lib/payment-providers";

export function PaymentProviderBadge({ provider }: { provider: string | null }) {
  const t = useTranslations("web.orders");
  const display = paymentProviderDisplay(provider);
  if (!display) return null;
  const label = display.nameKey ? t(display.nameKey) : (display.name ?? "");
  return (
    <span className="inline-flex items-center gap-1.5">
      {display.logo ? (
        <Image
          src={display.logo}
          alt={label}
          width={20}
          height={20}
          className="h-5 w-5 object-contain"
        />
      ) : null}
      <span>{label}</span>
    </span>
  );
}
```

- [ ] **Step 5: Run web unit tests + typecheck**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/payment-providers.test.ts && pnpm --filter @yupay/web exec tsc --noEmit`
Expected: PASS + clean.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/payment-providers.ts apps/web/src/lib/payment-providers.test.ts apps/web/src/lib/orders-types.ts apps/web/src/components/order/PaymentProviderBadge.tsx
git commit -m "feat(web/orders): payment-provider display map + badge

Map provider slugs to brand name + logo (Click/Payme/Uzum), text (Octo),
or a localized wallet label; add payment_provider to the web OrderOut type.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Web — order summary (money + provider + dates) + items, and account-list money fix

**Files:**

- Create: `apps/web/src/components/order/OrderSummary.tsx` (total paid, provider, dates)
- Create: `apps/web/src/components/order/OrderItems.tsx` (per-item: brand · what · qty · image)
- Modify: `apps/web/src/components/order/OrderStatus.tsx` (render `<OrderSummary>` + `<OrderItems>`; keep it the orchestrator)
- Modify: `apps/web/src/app/[locale]/account/orders/page.tsx:141` (money → `total_charged` + `currency`)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (`orders` namespace — summary/item/provider keys)
- Test: `apps/web/src/components/order/OrderSummary.test.tsx`

**Interfaces:**

- Consumes: `OrderOut` (now with `payment_provider`), `formatMoney` (`@yupay/utils`), `PaymentProviderBadge` (Task 3).
- Produces: `<OrderSummary order={order} />`, `<OrderItems items={order.items} />`.

- [ ] **Step 1: Add i18n keys (all three locales)**

Add to the `orders` namespace in `packages/i18n/locales/en/web.json` (and translate for ru/uz):

```json
"total": "Total paid",
"paidWith": "Paid with",
"paidWithWallet": "Balance",
"createdAt": "Created",
"paidAt": "Paid",
"deliveredAt": "Delivered",
"itemsTitle": "Items",
"qty": "Qty",
"receiptTitle": "Your delivery"
```

RU values: `"Оплачено"`, `"Способ оплаты"`, `"Баланс"`, `"Создан"`, `"Оплачен"`, `"Доставлен"`, `"Состав заказа"`, `"Кол-во"`, `"Ваша выдача"`.
UZ values: `"To‘langan"`, `"To‘lov usuli"`, `"Balans"`, `"Yaratilgan"`, `"To‘langan"`, `"Yetkazilgan"`, `"Buyurtma tarkibi"`, `"Soni"`, `"Yetkazma"`.

- [ ] **Step 2: Write the failing OrderSummary test**

Create `apps/web/src/components/order/OrderSummary.test.tsx` (jsdom + next-intl provider harness — mirror the existing test setup used by `OrderDeliveredModal.test.tsx` for the intl wrapper):

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OrderSummary } from "./OrderSummary";
import { renderWithIntl } from "@/test/intl"; // reuse the harness OrderDeliveredModal.test uses; if none, inline NextIntlClientProvider

const order = {
  id: "abcdef123456",
  status: "delivered",
  currency: "USD",
  total_usd: "10.00",
  total_charged: "10.00",
  payment_provider: "click",
  created_at: "2026-01-01T00:00:00Z",
  paid_at: "2026-01-01T00:01:00Z",
  delivered_at: "2026-01-01T00:02:00Z",
  // …minimal OrderOut; items: []
} as unknown as import("@/lib/orders-types").OrderOut;

describe("OrderSummary", () => {
  it("shows the total paid in the order currency and the provider", () => {
    renderWithIntl(<OrderSummary order={order} />);
    expect(screen.getByText("$10.00")).toBeInTheDocument();
    expect(screen.getByText("Click")).toBeInTheDocument();
  });
});
```

(If the repo has no shared `renderWithIntl`, inline a `NextIntlClientProvider` with the en `web` messages, exactly as `OrderDeliveredModal.test.tsx` does — copy that pattern.)

- [ ] **Step 3: Run and watch fail**

Run: `pnpm --filter @yupay/web exec vitest run src/components/order/OrderSummary.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 4: Build `OrderSummary`**

Create `apps/web/src/components/order/OrderSummary.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { formatMoney } from "@yupay/utils";
import type { OrderOut } from "@/lib/orders-types";
import { PaymentProviderBadge } from "./PaymentProviderBadge";

function fmtDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function OrderSummary({ order }: { order: OrderOut }) {
  const t = useTranslations("web.orders");
  const locale = useLocale();
  return (
    <dl className="grid grid-cols-2 gap-y-2 text-sm">
      <dt className="text-muted-foreground">{t("total")}</dt>
      <dd className="text-right font-semibold">
        {formatMoney(order.total_charged, order.currency, locale)}
      </dd>

      {order.payment_provider ? (
        <>
          <dt className="text-muted-foreground">{t("paidWith")}</dt>
          <dd className="flex justify-end">
            <PaymentProviderBadge provider={order.payment_provider} />
          </dd>
        </>
      ) : null}

      <dt className="text-muted-foreground">{t("createdAt")}</dt>
      <dd className="text-right">{fmtDate(order.created_at, locale)}</dd>

      {order.paid_at ? (
        <>
          <dt className="text-muted-foreground">{t("paidAt")}</dt>
          <dd className="text-right">{fmtDate(order.paid_at, locale)}</dd>
        </>
      ) : null}
      {order.delivered_at ? (
        <>
          <dt className="text-muted-foreground">{t("deliveredAt")}</dt>
          <dd className="text-right">{fmtDate(order.delivered_at, locale)}</dd>
        </>
      ) : null}
    </dl>
  );
}
```

- [ ] **Step 5: Build `OrderItems`**

Create `apps/web/src/components/order/OrderItems.tsx` — render each item's brand + denomination/region (from `display`), qty, and image if present. Port the visual shape from the miniapp `ItemCard` (`apps/miniapp/src/pages/OrderSuccess.tsx:649-720`) but simpler:

```tsx
"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import type { OrderItemOut } from "@/lib/orders-types";

function itemHeadline(item: OrderItemOut): string {
  const d = item.display;
  if (!d) return item.sku_id;
  const parts = [d.brand_name, d.denomination ?? d.product_name, d.region ?? undefined].filter(
    Boolean,
  );
  return parts.join(" · ");
}

export function OrderItems({ items }: { items: OrderItemOut[] }) {
  const t = useTranslations("web.orders");
  if (items.length === 0) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-muted-foreground text-sm font-medium">{t("itemsTitle")}</h3>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-3 rounded-lg border p-2">
            {item.display?.image_url ? (
              <Image
                src={item.display.image_url}
                alt=""
                width={40}
                height={40}
                className="h-10 w-10 rounded object-cover"
              />
            ) : null}
            <span className="flex-1 text-sm">{itemHeadline(item)}</span>
            {item.qty > 1 ? (
              <span className="text-muted-foreground text-xs">
                {t("qty")}: {item.qty}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 6: Wire into `OrderStatus.tsx`**

In `apps/web/src/components/order/OrderStatus.tsx`, import and render `<OrderSummary order={order} />` and `<OrderItems items={order.items} />` in the main body (below the status heading, above the artifact reveal). Do not remove existing behavior yet (status heading, artifact reveal, review CTA stay — the per-status StatusBlock is Task 5). Keep the file under 300 LOC by having it orchestrate the sub-components.

- [ ] **Step 7: Fix the account orders list money**

In `apps/web/src/app/[locale]/account/orders/page.tsx:141`, change `formatMoney(o.total_usd, "USD", locale)` → `formatMoney(o.total_charged, o.currency, locale)`.

- [ ] **Step 8: Run web tests + typecheck**

Run: `pnpm --filter @yupay/web exec vitest run src/components/order && pnpm --filter @yupay/web exec tsc --noEmit`
Expected: PASS + clean.

- [ ] **Step 9: Verify locale parity + commit**

Run the repo's i18n parity check if present (`pnpm --filter @yupay/i18n test` or the CI key-parity script) to confirm ru/en/uz all have the new keys.

```bash
git add apps/web/src/components/order/OrderSummary.tsx apps/web/src/components/order/OrderItems.tsx apps/web/src/components/order/OrderStatus.tsx apps/web/src/components/order/OrderSummary.test.tsx apps/web/src/app/[locale]/account/orders/page.tsx packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json
git commit -m "feat(web/orders): order summary (paid amount, provider, dates) + items

Show total_charged in the order currency (valid USD/UZS formatting), the
payment provider badge, order dates, and the item list on the details page;
fix the account orders list to show total_charged instead of total_usd.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 10: Controller visual verification (Playwright)** — NOTE FOR THE CONTROLLER, not the implementer: after review passes, drive Playwright against the running dev web (`http://localhost:3000`) to a paid/delivered order and confirm the total, provider badge, and dates render; capture a screenshot for the final report.

---

### Task 5: Web — per-status content (incl. fulfilling) + translated safe artifact reveal

**Files:**

- Create: `apps/web/src/components/order/StatusBlock.tsx` (per-status title + body copy, kind-aware where useful)
- Modify: `apps/web/src/components/order/OrderStatus.tsx` (use `<StatusBlock>`; replace the bare status heading; clean up the artifact reveal to translated, whitelisted-only display)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (`orders.body.*` per-status copy + artifact/receipt labels)
- Test: `apps/web/src/components/order/StatusBlock.test.tsx`

**Interfaces:**

- Consumes: `OrderOut.status`, item kinds (`display.product_kind`).
- Produces: `<StatusBlock status={order.status} order={order} />`.

- [ ] **Step 1: Add per-status body copy (all three locales)**

Add an `orders.body` object keyed by status. EN example (translate ru/uz):

```json
"body": {
  "pending_payment": "Waiting for your payment.",
  "paid": "Payment received — preparing your order.",
  "fulfilling": "Payment accepted. We're delivering your order — usually automatic and quick. Support is on standby if anything's off.",
  "fulfilled": "Your order is ready.",
  "delivered": "Delivered. Your items are below.",
  "failed": "Something went wrong. Our team is on it — contact support if you need help.",
  "cancelled": "This order was cancelled.",
  "expired": "This order expired before payment.",
  "refunded": "This order was refunded.",
  "partially_refunded": "This order was partially refunded."
}
```

RU `fulfilling`: `"Оплата принята. Выдаём заказ — обычно автоматически и быстро. Если что-то пойдёт не так, поддержка на связи."` (translate the rest similarly). UZ likewise.

- [ ] **Step 2: Write the failing StatusBlock test**

Create `apps/web/src/components/order/StatusBlock.test.tsx` — assert the `fulfilling` status renders the body copy, not just the status word:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBlock } from "./StatusBlock";
import { renderWithIntl } from "@/test/intl"; // or inline NextIntlClientProvider per OrderDeliveredModal.test

describe("StatusBlock", () => {
  it("shows real body copy for a fulfilling order (not just the status word)", () => {
    renderWithIntl(<StatusBlock status="fulfilling" />);
    expect(screen.getByText(/delivering your order/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run and watch fail**

Run: `pnpm --filter @yupay/web exec vitest run src/components/order/StatusBlock.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 4: Build `StatusBlock`**

Create `apps/web/src/components/order/StatusBlock.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";

const KNOWN = new Set([
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
  "delivered",
  "failed",
  "cancelled",
  "expired",
  "refunded",
  "partially_refunded",
]);

export function StatusBlock({ status }: { status: string }) {
  const t = useTranslations("web.orders");
  const known = KNOWN.has(status);
  return (
    <div className="space-y-1">
      <h2 className="text-lg font-semibold">{known ? t(`status.${status}`) : status}</h2>
      {known ? <p className="text-muted-foreground text-sm">{t(`body.${status}`)}</p> : null}
    </div>
  );
}
```

- [ ] **Step 5: Clean the artifact reveal to translated + whitelisted-only**

In `apps/web/src/components/order/OrderStatus.tsx`, replace the raw `ArtifactReveal` dump behavior: since Phase 1 already guarantees only whitelisted keys arrive, render each known key with a TRANSLATED label (map key → i18n `orders.receipt.<key>`), keep `CopyChip` for copyable values (`code`/`codes`/`key`/`pin`/`serial`/`login`/`steam_login`), render `message`/`note` as plain text, and render `fulfillment_data` (the customer's own input) via the existing labeled rows. Remove the `JSON.stringify` fallback branch entirely — there are no unknown keys to fall back on anymore. Add `orders.receipt.*` labels to all three locales (EN: `code`→"Code", `key`→"Key", `pin`→"PIN", `serial`→"Serial", `steam_login`→"Steam login", `login`→"Login", `message`→"Message"; ru/uz translated). Replace the `humanizeKey` raw-key label with a lookup into `orders.receipt.*` (fall back to the key only if unmapped).

- [ ] **Step 6: Swap the heading + run tests**

In `OrderStatus.tsx`, replace the bare status heading (`t('status.${status}')`) with `<StatusBlock status={status} />`.
Run: `pnpm --filter @yupay/web exec vitest run src/components/order && pnpm --filter @yupay/web exec tsc --noEmit`
Expected: PASS + clean. Confirm `OrderStatus.tsx` is under 300 LOC (it should shrink — logic moved to sub-components).

- [ ] **Step 7: Locale parity + commit**

Run the i18n parity check.

```bash
git add apps/web/src/components/order/StatusBlock.tsx apps/web/src/components/order/StatusBlock.test.tsx apps/web/src/components/order/OrderStatus.tsx packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json
git commit -m "feat(web/orders): per-status content + translated safe artifact reveal

Give every order status real body copy (incl. a proper 'fulfilling' state)
and render the delivered artifact with translated labels over Phase-1's
whitelisted keys only — no raw key dump, no JSON fallback.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 8: Controller visual verification (Playwright)** — NOTE FOR THE CONTROLLER: drive Playwright to a `fulfilling` order (confirm body copy) and a `delivered` order (confirm translated receipt, copyable code, NO `source`/raw keys visible); capture screenshots for the final report.

---

### Task 6: Mini App — payment-provider parity + tidy artifact fallback

**Files:**

- Modify: `apps/miniapp/src/lib/orders.ts` (add `payment_provider: string | null` to `OrderOut`)
- Modify: `apps/miniapp/src/pages/OrderSuccess.tsx` (Summary — add a provider row; `ArtifactBlock` — drop the raw `JSON.stringify` fallback)
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (flat `success.paidWith` + `success.paidWithWallet` keys; RU canonical)
- Test: extend an existing miniapp test if the suite covers `OrderSuccess`, else add a focused unit test for a `providerLabel(provider)` helper.

**Interfaces:**

- Consumes: `OrderOut.payment_provider` (Task 1 backend field).
- Produces: a provider row in the miniapp order Summary; no raw-JSON artifact dump.

- [ ] **Step 1: Add the type field**

In `apps/miniapp/src/lib/orders.ts`, add `payment_provider: string | null;` to `OrderOut` (near `total_charged`/`currency`).

- [ ] **Step 2: Add miniapp i18n keys (RU canonical, en/uz)**

In `packages/i18n/locales/ru/miniapp.json` add flat keys: `"success.paidWith": "Способ оплаты"`, `"success.paidWithWallet": "Баланс"`. Mirror in en (`"Paid with"`, `"Balance"`) and uz (`"To‘lov usuli"`, `"Balans"`).

- [ ] **Step 3: Add a small provider-label helper + render the row**

In `apps/miniapp/src/pages/OrderSuccess.tsx`, add a helper that maps a provider slug to a display string (Click/Payme/Uzum/Octo brand names; `wallet` → `translate("success.paidWithWallet")`; `click_miniapp`→Click; unknown → the slug; `null`→null), and add a row to the `Summary` component (`:965-988`) after the total:

```tsx
{
  order.payment_provider ? (
    <SummaryRow
      label={translate("success.paidWith")}
      value={providerLabel(order.payment_provider)}
    />
  ) : null;
}
```

(Use the Summary's existing row markup — mirror the `createdAt`/`paidAt` rows at `:980-982`; there are no provider logo assets in `apps/miniapp/public/`, so this is a text value.)

- [ ] **Step 4: Drop the raw JSON artifact fallback**

In `ArtifactBlock` (`apps/miniapp/src/pages/OrderSuccess.tsx:~903-913`), remove the `JSON.stringify(delivery.artifact, null, 2)` `<pre>` fallback. After Phase 1 the artifact carries only whitelisted keys; render the known ones (code/key + receipt) as it already does, and if none match, render nothing (or a simple translated "delivered" line) instead of dumping the object.

- [ ] **Step 5: Typecheck + test + commit**

Run: `pnpm --filter @yupay/miniapp exec tsc --noEmit` and the miniapp test suite (`pnpm --filter @yupay/miniapp test` or vitest run).

```bash
git add apps/miniapp/src/lib/orders.ts apps/miniapp/src/pages/OrderSuccess.tsx packages/i18n/locales/ru/miniapp.json packages/i18n/locales/en/miniapp.json packages/i18n/locales/uz/miniapp.json
git commit -m "feat(miniapp/orders): show payment provider + drop raw artifact JSON dump

Add the payment provider to the order summary (parity with web) and remove
the JSON.stringify artifact fallback — Phase 1 already guarantees only
customer-safe artifact keys reach the client.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Controller visual verification (Playwright)** — NOTE FOR THE CONTROLLER: drive Playwright against the miniapp dev (`http://localhost:3001`) to an order and confirm the provider row renders and no raw JSON is shown; screenshot for the final report.

---

## Self-Review

- **Spec coverage (Phase 2 section):** payment_provider on OrderOut ✅ Task 1; provider→name/logo map ✅ Task 3; per-status content incl fulfilling ✅ Task 5; total_charged + currency formatted (USD `$X.XX`, UZS zero-dec) ✅ Task 2 (util) + Task 4 (summary); provider logo/text ✅ Task 3 badge + Task 4 summary; items from display ✅ Task 4; dates ✅ Task 4; translated safe artifact reveal (deliverable + receipt, whitelisted only, no raw dump) ✅ Task 5; i18n ru/en/uz ✅ Tasks 4/5/6; account list money fix ✅ Task 4; miniapp provider parity + close ArtifactBlock JSON fallback ✅ Task 6; Playwright per visible fix ✅ controller steps 4.10/5.8/6.6 + final report.
- **Placeholder scan:** the i18n steps give real copy for EN + RU (+ UZ where short); the implementer must fill any UZ value not spelled out — flagged explicitly in each i18n step, not left as "TBD".
- **Type consistency:** `payment_provider` is `str | None` (api) / `string | null` (web+miniapp); `paymentProviderDisplay` returns `{name?|nameKey?|logo?}` used identically by the badge (web) and mirrored by `providerLabel` (miniapp text-only); `formatMoney(amount, currency, locale)` signature unchanged and used the same way in summary + account list.
- **N+1 guard:** Task 1 uses `selectinload(Order.payments)` + `lazy="raise"` so any missed eager-load fails loudly in tests; Step 7 adds the explicit list guard.
- **LOC:** the web rework moves logic OUT of `OrderStatus.tsx` into `OrderSummary`/`OrderItems`/`StatusBlock`/`PaymentProviderBadge`, keeping every file under the 300-LOC soft limit.
- **Note for executor:** the `renderWithIntl` harness may not exist as a shared util — each web component test says to reuse the `NextIntlClientProvider` pattern already in `OrderDeliveredModal.test.tsx`; confirm that file's approach before writing the first test.
