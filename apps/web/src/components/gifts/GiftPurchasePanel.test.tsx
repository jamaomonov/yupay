// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { GiftPurchasePanel } from "./GiftPurchasePanel";

import type * as GiftCheckoutModule from "@/lib/gift-checkout";
import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";

import { buyGift, GiftPriceChangedError } from "@/lib/gift-checkout";
import { countryName } from "@/lib/regions";
import { formatUzs } from "@/lib/seo";

/**
 * The Steam gift purchase panel: edition/region pickers re-price from the
 * detail payload already on the page (no round trip just to switch zones),
 * a client-side invite-link gate blocks submit before it ever reaches
 * `lib/gift-checkout.ts`, and a price-drift 422 (surfaced as
 * `GiftPriceChangedError`) refreshes the page instead of retrying blind.
 */

vi.mock("next-intl", () => ({
  useTranslations: () =>
    Object.assign(
      (k: string, values?: Record<string, unknown>) =>
        values ? `${k}:${JSON.stringify(values)}` : k,
      // `InviteGuide` (rendered inside the panel) reads its steps via
      // `t.raw()` — the plain passthrough above has no such method.
      { raw: (k: string) => (k === "inviteGuideSteps" ? ["Step one", "Step two"] : k) },
    ),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: null }),
}));

// `vi.mock` factories are hoisted above the file's own top-level `const`s, so
// the mock functions they close over must be created through `vi.hoisted`
// rather than declared as plain module-level `const`s.
const { pushMock, refreshMock, toastInfoMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  refreshMock: vi.fn(),
  toastInfoMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

vi.mock("@/store/useToast", () => ({
  toast: { info: toastInfoMock, success: vi.fn(), error: vi.fn() },
}));

// Only `buyGift` is stubbed — `GiftPriceChangedError` stays the real class so
// the panel's `err instanceof GiftPriceChangedError` check still works.
vi.mock("@/lib/gift-checkout", async (importOriginal) => ({
  ...(await importOriginal<typeof GiftCheckoutModule>()),
  buyGift: vi.fn(),
}));

const buyGiftMock = vi.mocked(buyGift);

function mockProvidersResponse(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ providers: [{ slug: "click", status: "active" }] }),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  buyGiftMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
  toastInfoMock.mockReset();
});

const STANDARD_EDITION: GiftPackage = {
  id: 1,
  name: "Standard Edition",
  image: null,
  discount_percent: null,
  prices: [
    { zone: "CIS", price_usd: "1.10", price_uzs: "13970" },
    { zone: "RU", price_usd: "1.30", price_uzs: "16510" },
  ],
};

function makeDetail(overrides: Partial<GiftAppDetail> = {}): GiftAppDetail {
  return {
    app_id: 588650,
    name: "Dead Cells",
    image: null,
    type: "game",
    price_usd: "1.10",
    price_uzs: "13970",
    discount_percent: null,
    packages_count: 1,
    dlc_count: 2,
    description: "A rogue-lite.",
    packages: [STANDARD_EDITION],
    dlc_total: 2,
    regions: [
      { country: "UZ", zone: "CIS", price_usd: "1.10", price_uzs: "13970" },
      { country: "GE", zone: "CIS", price_usd: "1.10", price_uzs: "13970" },
      { country: "RU", zone: "RU", price_usd: "1.30", price_uzs: "16510" },
    ],
    region_default: "UZ",
    ...overrides,
  };
}

/** Accessible name of the country pill for `code`, as `useTranslations`'
 *  plain-passthrough mock renders it (see the `next-intl` mock above) — the
 *  flag emoji plus the `ru`-localized country name. */
function countryButtonName(code: string): RegExp {
  return new RegExp(countryName(code, "ru"));
}

/** `formatUzs` renders `Intl.NumberFormat`'s U+00A0 grouping separator, but
 *  Testing Library's default text normalizer collapses `\s+` (which matches
 *  NBSP) to a plain space on the *rendered* node without touching a plain
 *  string matcher the same way — so a raw `formatUzs(...)` string never
 *  matches the DOM. Normalize the expectation the same way to compare like
 *  with like. */
function priceText(amount: number): string {
  return formatUzs("ru", amount).replace(/\u00a0/g, " ");
}

async function fillValidCheckout(): Promise<void> {
  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "guest@example.com" },
  });
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "buy" })).not.toBeDisabled();
  });
}

it("renders the default country's (UZ) price", () => {
  mockProvidersResponse();
  render(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  expect(screen.getAllByText(priceText(13970)).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: countryButtonName("UZ") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("re-prices when the country is switched", () => {
  mockProvidersResponse();
  render(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));

  expect(screen.getAllByText(priceText(16510)).length).toBeGreaterThan(0);
  expect(screen.queryByText(priceText(13970))).not.toBeInTheDocument();
});

it("disables a country whose zone has no price for the selected package, with visible text", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: "13970" }] },
    ],
  });
  render(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  const ruButton = screen.getByRole("button", { name: countryButtonName("RU") });
  expect(ruButton).toBeDisabled();
  // Visible text, not a `title=` tooltip (invisible on mobile) — see
  // `CountryButton` in `GiftPurchasePanel.tsx`.
  expect(ruButton).not.toHaveAttribute("title");
  expect(screen.getByText("noPriceInRegion")).toBeInTheDocument();
});

it("blocks submit and shows the i18n error on a bad invite URL", () => {
  mockProvidersResponse();
  render(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://example.com/not-steam" },
  });

  expect(screen.getByText("inviteError")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "buy" })).toBeDisabled();
  expect(buyGiftMock).not.toHaveBeenCalled();
});

it("POSTs the exact checkout body via lib/gift-checkout on submit", async () => {
  mockProvidersResponse();
  buyGiftMock.mockResolvedValue({
    orderId: "order-1",
    // `null` — as the dev `mock` provider returns — so the panel routes via
    // `router.push` instead of `window.location.href`, which jsdom doesn't
    // implement.
    intentUrl: null,
    trackHref: "/orders/order-1?email=guest%40example.com",
  });
  render(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  expect(buyGiftMock).toHaveBeenCalledWith({
    locale: "ru",
    skuId: "sku-1",
    amountUsd: "1.10",
    fulfillmentData: {
      app_id: 588650,
      package_id: 1,
      region: "UZ",
      invite_url: "https://steamcommunity.com/profiles/76561198000000000",
    },
    email: "guest@example.com",
    isLoggedIn: false,
    provider: "click",
    gameName: "Dead Cells",
  });
});

it("shows the price-changed toast and refreshes on a 422 price-drift error", async () => {
  mockProvidersResponse();
  buyGiftMock.mockRejectedValue(new GiftPriceChangedError("1.25"));
  render(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  await waitFor(() => {
    expect(toastInfoMock).toHaveBeenCalledWith("priceChanged");
  });
  expect(refreshMock).toHaveBeenCalledTimes(1);
  expect(pushMock).not.toHaveBeenCalled();
});
