// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { GiftPurchasePanel } from "./GiftPurchasePanel";

import type { Me } from "@/lib/auth";
import type * as GiftCheckoutModule from "@/lib/gift-checkout";
import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";

import { ApiError, clearTokens, setTokens } from "@/lib/client";
import { buyGift, GiftPriceChangedError } from "@/lib/gift-checkout";
import { countryName } from "@/lib/regions";
import { formatUzs } from "@/lib/seo";
import { useLoginModal } from "@/store/useLoginModal";

/**
 * The Steam gift purchase panel: edition/region pickers re-price from the
 * detail payload already on the page (no round trip just to switch zones),
 * a client-side invite-link gate blocks submit before it ever reaches
 * `lib/gift-checkout.ts`, a price-drift 422 (surfaced as
 * `GiftPriceChangedError`) refreshes the page instead of retrying blind, and
 * a "pay from balance" tile mirrors `PurchasePanel`'s (ready/short/guest
 * states, the reselect-effect guard, a surfaced 409 detail).
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

// `vi.mock` factories are hoisted above the file's own top-level `const`s, so
// the mock functions they close over must be created through `vi.hoisted`
// rather than declared as plain module-level `const`s.
const { pushMock, refreshMock, toastInfoMock, useAuthMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  refreshMock: vi.fn(),
  toastInfoMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: useAuthMock,
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

/**
 * `fetch` stub for the wallet-pay tests: routes `/wallet` to a balance
 * response (mirroring `apiFetch`'s `{ ok, status, json }` shape) and
 * everything else to the raw providers response `GiftPurchasePanel`'s own
 * `fetch` call reads directly. Defaults every provider (including `wallet`)
 * to `active`; pass `providers` to simulate admin maintenance/disable.
 */
function mockWallet(
  balance: string | null,
  providers: { slug: string; status: "active" | "maintenance" }[] = [
    { slug: "click", status: "active" },
    { slug: "wallet", status: "active" },
  ],
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url.includes("/wallet")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              balances:
                balance === null
                  ? []
                  : [{ account_id: "acc-1", kind: "user_wallet", currency: "UZS", balance }],
            }),
        });
      }
      return Promise.resolve({ json: () => Promise.resolve({ providers }) });
    }),
  );
}

function makeUser(overrides: Partial<Me> = {}): Me {
  return {
    id: "user-1",
    email: "user@example.com",
    delivery_email: null,
    locale: "ru",
    display_currency: "UZS",
    display_name: "User",
    photo_url: null,
    roles: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** The panel reads the wallet balance through react-query, so every render
 *  needs a client. Retries off so a mocked failure fails once instead of
 *  stalling the test. */
function renderPanel(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
  buyGiftMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
  toastInfoMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: null, isLoading: false });
  useLoginModal.setState({ isOpen: false });
  clearTokens();
});

useAuthMock.mockReturnValue({ user: null, isLoading: false });

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

/** A second edition still priced in both offered zones, but at different
 *  numbers than `STANDARD_EDITION` — so a re-price after a package switch
 *  is distinguishable from "the country silently reset". */
const MULTI_REGION_EDITION: GiftPackage = {
  id: 2,
  name: "Multi-Region Edition",
  image: null,
  discount_percent: null,
  prices: [
    { zone: "CIS", price_usd: "1.20", price_uzs: "15240" },
    { zone: "RU", price_usd: "1.45", price_uzs: "18400" },
  ],
};

/** A third edition priced only in CIS — switching to it from an RU
 *  selection must trip the `selectPackage` fallback. */
const CIS_ONLY_EDITION: GiftPackage = {
  id: 3,
  name: "CIS-Only Edition",
  image: null,
  discount_percent: null,
  prices: [{ zone: "CIS", price_usd: "0.90", price_uzs: "11430" }],
};

/** A fourth edition (a "deluxe" package) priced only in RU — neither the
 *  default country's zone (UZ -> CIS) nor, when the buyer hasn't moved off
 *  the default, the current country's zone prices it. Switching to it must
 *  fall through to the third fallback step (a country covering the
 *  package's own first priced zone), not strand the buyer on a disabled
 *  Buy button. */
const RU_ONLY_EDITION: GiftPackage = {
  id: 4,
  name: "RU-Only Deluxe Edition",
  image: null,
  discount_percent: null,
  prices: [{ zone: "RU", price_usd: "0.95", price_uzs: "12065" }],
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

/** A detail payload from an API version that predates `regions`/
 *  `region_default` (2026-09-03): the keys are omitted entirely, not set
 *  to `undefined` — `exactOptionalPropertyTypes` treats those differently,
 *  and the real shape a stale API's JSON body would have is "key absent",
 *  same as `apiGet`'s unchecked cast would let through in prod during a
 *  rolling deploy's version-skew window. */
function makeDetailWithoutRegions(): GiftAppDetail {
  const { regions: _regions, region_default: _regionDefault, ...rest } = makeDetail();
  return rest;
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
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  expect(screen.getAllByText(priceText(13970)).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: countryButtonName("UZ") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

/**
 * The gift panel used to print the UZS charge and a USD figure
 * (`price_usd`) side by side — the buyer had no way to tell which one
 * actually left their account (it is always UZS; `buyGift` hardcodes
 * `currency: "UZS"`). Both the main price row and the per-package edition
 * rows must show exactly one currency (2026-09-04 review).
 */
it("shows only the UZS figure on the main price row — no USD figure anywhere on the panel", () => {
  mockProvidersResponse();
  // `makeDetail()`'s `STANDARD_EDITION` also carries `price_usd: "1.10"` — a
  // leftover dollar figure would surface as a literal "$" somewhere on the
  // page.
  const { container } = renderPanel(
    <GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />,
  );

  expect(screen.getAllByText(priceText(13970)).length).toBeGreaterThan(0);
  expect(container.textContent).not.toMatch(/\$/);
  expect(container.textContent).not.toMatch(/1[.,]10/);
});

it("shows a dash, never the USD figure, on a package row whose price is FX-down", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: null }] },
    ],
  });
  const { container } = renderPanel(
    <GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />,
  );

  expect(screen.getByRole("button", { name: /Standard Edition/ })).toHaveTextContent("—");
  expect(container.textContent).not.toMatch(/\$/);
  expect(container.textContent).not.toMatch(/1[.,]10/);
});

it("re-prices when the country is switched", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

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
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  const ruButton = screen.getByRole("button", { name: countryButtonName("RU") });
  expect(ruButton).toBeDisabled();
  // Visible text, not a `title=` tooltip (invisible on mobile) — see
  // `CountryButton` in `GiftPurchasePanel.tsx`.
  expect(ruButton).not.toHaveAttribute("title");
  expect(screen.getByText("noPriceInRegion")).toBeInTheDocument();
});

it("renders the coming-soon state instead of crashing when the API predates `regions`", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetailWithoutRegions()} skuId="sku-1" locale="ru" />);

  expect(screen.getByText("comingSoon")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "buy" })).not.toBeInTheDocument();
});

it("keeps the selected country across a package switch when its zone is still priced", () => {
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, MULTI_REGION_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  fireEvent.click(screen.getByRole("button", { name: /Multi-Region Edition/ }));

  expect(screen.getByRole("button", { name: countryButtonName("RU") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // The new package's own RU price, not its CIS price and not the old
  // package's RU price — proves the country stayed RU through the switch
  // rather than silently resetting to `region_default`.
  expect(screen.getAllByText(priceText(18400)).length).toBeGreaterThan(0);
});

it("falls back to region_default when the new package no longer prices the selected country's zone", () => {
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, CIS_ONLY_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  fireEvent.click(screen.getByRole("button", { name: /CIS-Only Edition/ }));

  expect(screen.getByRole("button", { name: countryButtonName("UZ") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: countryButtonName("RU") })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(screen.getAllByText(priceText(11430)).length).toBeGreaterThan(0);
});

it("falls through to a priced country when a package switch prices neither the current nor the default country's zone", () => {
  // Real scenario this guards against: package A priced CIS+RU, package B
  // (deluxe) priced RU only; buyer sits on the default (UZ, CIS) and
  // switches to B. The old web-only fallback (current -> region_default)
  // stopped at region_default, which B doesn't price either, and left the
  // buyer on UZ with a disabled Buy button — the miniapp already had a
  // third step (a country covering the package's own priced zone) that
  // avoided this. Mirrors miniapp `GiftGame.test.tsx`'s
  // `countryAfterPackageChange` RU-fallback case.
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, RU_ONLY_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: /RU-Only Deluxe Edition/ }));

  expect(screen.getByRole("button", { name: countryButtonName("RU") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: countryButtonName("UZ") })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(screen.getAllByText(priceText(12065)).length).toBeGreaterThan(0);
});

it("blocks Buy and shows the price-unavailable card when FX is down for the selected price", () => {
  mockProvidersResponse();
  // `price_uzs: null` — the FX trust gate rejected the live rate for this
  // zone. `price_usd` is still present, which is exactly the trap: the old
  // behaviour fell back to showing it as if it were payable.
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: null }] },
    ],
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  expect(screen.getByText("priceUnavailable")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "guest@example.com" },
  });
  // Never enabled — a valid invite and email are not enough while FX is down.
  expect(screen.getByRole("button", { name: "buy" })).toBeDisabled();
  expect(buyGiftMock).not.toHaveBeenCalled();
});

it("shows FX-down wording on the wallet tile instead of 'choose a package' when the picked price has no UZS conversion", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  mockWallet("50000");
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: null }] },
    ],
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  // The package IS chosen — `walletTile` must not say `noTotal`'s "choose a
  // package" here, only that FX is down.
  await waitFor(() => {
    expect(walletTileButton()).toHaveTextContent("priceUnavailable");
  });
  expect(walletTileButton()).not.toHaveTextContent("payFromBalanceUnknown");
  expect(walletTileButton()).toBeDisabled();
});

it("shows the edition-switch notice only when picking an edition actually moves the buyer's country", () => {
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, CIS_ONLY_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  expect(screen.queryByText(/editionSwitchNotice/)).not.toBeInTheDocument();

  // CIS_ONLY_EDITION doesn't price RU — `selectPackage` falls back to
  // `region_default` (UZ), moving the country out from under the buyer.
  fireEvent.click(screen.getByRole("button", { name: /CIS-Only Edition/ }));

  expect(
    screen.getByText(`editionSwitchNotice:${JSON.stringify({ country: countryName("UZ", "ru") })}`),
  ).toBeInTheDocument();
});

it("does not show the edition-switch notice when the new edition still prices the buyer's current country", () => {
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, MULTI_REGION_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  fireEvent.click(screen.getByRole("button", { name: /Multi-Region Edition/ }));

  expect(screen.queryByText(/editionSwitchNotice/)).not.toBeInTheDocument();
});

it("clears a stale edition-switch notice once the buyer manually repicks a country", () => {
  mockProvidersResponse();
  const detail = makeDetail({ packages: [STANDARD_EDITION, CIS_ONLY_EDITION] });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  fireEvent.click(screen.getByRole("button", { name: /CIS-Only Edition/ }));
  expect(screen.getByText(/editionSwitchNotice/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("UZ") }));
  expect(screen.queryByText(/editionSwitchNotice/)).not.toBeInTheDocument();
});

it("shows a visible maintenance strip on a disabled acquirer tile, not a title tooltip", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      json: () =>
        Promise.resolve({
          providers: [
            { slug: "click", status: "active" },
            { slug: "payme", status: "maintenance" },
          ],
        }),
    }),
  );
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const payme = await screen.findByRole("button", { name: "Payme" });
  await waitFor(() => {
    expect(payme).toBeDisabled();
  });
  expect(payme).not.toHaveAttribute("title");
  expect(payme).toHaveTextContent("paymentMaintenanceShort");
});

it("blocks submit and shows the i18n error on a bad invite URL", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://example.com/not-steam" },
  });

  expect(screen.getByText("inviteError")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "buy" })).toBeDisabled();
  expect(buyGiftMock).not.toHaveBeenCalled();
});

it("announces the invite error via aria-invalid/aria-describedby, not just a floating paragraph", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const inviteInput = screen.getByLabelText("inviteLabel");
  fireEvent.change(inviteInput, { target: { value: "https://example.com/not-steam" } });

  const err = screen.getByText("inviteError");
  expect(inviteInput).toHaveAttribute("aria-invalid", "true");
  expect(inviteInput).toHaveAttribute("aria-describedby", err.id);
  expect(err.id).not.toBe("");
});

it("shows a visible, announced error for an invalid guest email and blocks Buy", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const emailInput = screen.getByLabelText("emailLabel");
  // Untouched — no error yet, a blank required field is a different state
  // from a mistyped one.
  expect(screen.queryByText("emailInvalid")).not.toBeInTheDocument();

  fireEvent.change(emailInput, { target: { value: "not-an-email" } });

  const err = screen.getByText("emailInvalid");
  expect(emailInput).toHaveAttribute("aria-invalid", "true");
  expect(emailInput).toHaveAttribute("aria-describedby", err.id);
  expect(emailInput).toHaveAttribute("autoComplete", "email");

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
  expect(screen.getByRole("button", { name: "buy" })).toBeDisabled();
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
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  // `idempotencyKey` is asserted separately below — its stickiness across
  // retries and resets is what the sticky-order-key tests further down
  // cover; here it only needs to be a non-empty string.
  expect(buyGiftMock).toHaveBeenCalledWith(
    expect.objectContaining({
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
    }),
  );
  expect(typeof buyGiftMock.mock.calls[0]?.[0].idempotencyKey).toBe("string");
  expect(buyGiftMock.mock.calls[0]?.[0].idempotencyKey).not.toBe("");
});

it("shows the price-changed toast and refreshes on a 422 price-drift error", async () => {
  mockProvidersResponse();
  buyGiftMock.mockRejectedValue(new GiftPriceChangedError("1.25"));
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  await waitFor(() => {
    expect(toastInfoMock).toHaveBeenCalledWith("priceChanged");
  });
  expect(refreshMock).toHaveBeenCalledTimes(1);
  expect(pushMock).not.toHaveBeenCalled();
});

// ---------- pay from balance ----------

/** A signed-in buyer has no email field to fill — only the invite link. */
function fillInviteOnly(): void {
  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
}

function walletTileButton() {
  return screen.getByRole("button", { name: /payFromBalance/ });
}

it("shows the wallet tile as ready for a signed-in buyer and pays with provider: wallet", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  mockWallet("50000");
  buyGiftMock.mockResolvedValue({
    orderId: "order-1",
    intentUrl: null,
    trackHref: "/orders/order-1",
  });
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  // UZ (region_default) prices this package at 13 970 — well under the
  // 50 000 balance, so the tile settles on `ready` once the balance loads.
  await waitFor(() => {
    expect(walletTileButton()).not.toBeDisabled();
  });
  expect(walletTileButton()).toHaveTextContent(priceText(50000));

  fireEvent.click(walletTileButton());
  expect(walletTileButton()).toHaveAttribute("aria-pressed", "true");

  fillInviteOnly();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  expect(buyGiftMock).toHaveBeenCalledWith(
    expect.objectContaining({ provider: "wallet", isLoggedIn: true }),
  );
  await waitFor(() => {
    expect(pushMock).toHaveBeenCalledWith("/orders/order-1");
  });
});

it("disables the wallet tile and offers a top-up link when the balance is short", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  // UZ prices the package at 13 970 — this balance is short by 3 970.
  mockWallet("10000");
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await waitFor(() => {
    expect(walletTileButton()).toHaveTextContent("payFromBalanceShort");
  });
  expect(walletTileButton()).toBeDisabled();

  const topUp = screen.getByRole("link", { name: /payFromBalanceTopUp/ });
  expect(topUp).toHaveAttribute("href", "/account/wallet/top-up");

  // Clicking a disabled tile is a no-op — the click acquirer stays selected.
  fireEvent.click(walletTileButton());
  fillInviteOnly();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  expect(buyGiftMock).toHaveBeenCalledWith(expect.objectContaining({ provider: "click" }));
});

it("asks a guest to sign in rather than offering an account they do not have", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const tile = walletTileButton();
  expect(tile).not.toBeDisabled();
  expect(tile).toHaveTextContent("payFromBalanceGuest");

  fireEvent.click(tile);
  expect(useLoginModal.getState().isOpen).toBe(true);
  // A guest token must never reach `provider: "wallet"` — the tap opened the
  // login modal instead of selecting the tile as the payment method.
  expect(tile).not.toHaveAttribute("aria-pressed", "true");
});

it("surfaces a 409's detail instead of the generic buy error", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  mockWallet("50000");
  buyGiftMock.mockRejectedValue(
    new ApiError(
      409,
      "/payments/intents",
      undefined,
      "insufficient wallet balance: have 10000 UZS, need 13970 UZS",
    ),
  );
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await waitFor(() => {
    expect(walletTileButton()).not.toBeDisabled();
  });
  fireEvent.click(walletTileButton());
  fillInviteOnly();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  expect(
    await screen.findByText("insufficient wallet balance: have 10000 UZS, need 13970 UZS"),
  ).toBeInTheDocument();
  expect(pushMock).not.toHaveBeenCalled();
});

// ---------- sticky order idempotency key ----------

/** The order-key params `handleBuy` builds `buyGift` calls from — everything
 *  but `idempotencyKey`, which each test reads off the mock call instead. */
function orderKeyOf(call: number): string {
  const args = buyGiftMock.mock.calls[call]?.[0];
  if (!args) throw new Error(`buyGift was not called a ${String(call + 1)}th time`);
  return args.idempotencyKey;
}

it("sends the same Idempotency-Key across two consecutive failed attempts with unchanged inputs", async () => {
  mockProvidersResponse();
  buyGiftMock.mockRejectedValue(new Error("network blip"));
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });

  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(2);
  });

  expect(orderKeyOf(1)).toBe(orderKeyOf(0));
});

it("mints a different Idempotency-Key when the region changes between attempts", async () => {
  mockProvidersResponse();
  buyGiftMock.mockRejectedValue(new Error("network blip"));
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(2);
  });

  expect(orderKeyOf(1)).not.toBe(orderKeyOf(0));
});

it("keeps the same Idempotency-Key when only the payment method changes between attempts", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      json: () =>
        Promise.resolve({
          providers: [
            { slug: "click", status: "active" },
            { slug: "payme", status: "active" },
          ],
        }),
    }),
  );
  buyGiftMock.mockRejectedValue(new Error("network blip"));
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  expect(orderKeyOf(0)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Payme" }));
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(2);
  });

  expect(orderKeyOf(1)).toBe(orderKeyOf(0));
  // Confirms the two calls really did request different providers — this is
  // not just an accidental no-op click.
  expect(buyGiftMock.mock.calls[0]?.[0].provider).toBe("click");
  expect(buyGiftMock.mock.calls[1]?.[0].provider).toBe("payme");
});

it("mints a fresh Idempotency-Key for the next purchase after a success", async () => {
  mockProvidersResponse();
  buyGiftMock.mockResolvedValue({
    orderId: "order-1",
    intentUrl: null,
    trackHref: "/orders/order-1?email=guest%40example.com",
  });
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  const firstKey = orderKeyOf(0);

  // Same inputs, a second purchase after the first succeeded.
  fireEvent.click(screen.getByRole("button", { name: "buy" }));
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(2);
  });

  expect(orderKeyOf(1)).not.toBe(firstKey);
});

it("retries exactly once with a fresh key when the order is no longer awaiting payment", async () => {
  mockProvidersResponse();
  const staleOrderConflict = new ApiError(
    409,
    "/payments/intents",
    undefined,
    "order is not awaiting payment",
    { status: "expired" },
  );
  buyGiftMock.mockRejectedValueOnce(staleOrderConflict).mockResolvedValueOnce({
    orderId: "order-2",
    intentUrl: null,
    trackHref: "/orders/order-2?email=guest%40example.com",
  });
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  // Exactly one automatic retry — a single click, two calls, no third.
  await waitFor(() => {
    expect(pushMock).toHaveBeenCalledWith("/orders/order-2?email=guest%40example.com");
  });
  expect(buyGiftMock).toHaveBeenCalledTimes(2);
  expect(orderKeyOf(1)).not.toBe(orderKeyOf(0));
  // The retry is invisible — no error text left over from the first attempt.
  expect(screen.queryByText("order is not awaiting payment")).not.toBeInTheDocument();
});

it("surfaces the error normally when the retried attempt also fails, without a third call", async () => {
  mockProvidersResponse();
  const staleOrderConflict = () =>
    new ApiError(409, "/payments/intents", undefined, "order is not awaiting payment", {
      status: "expired",
    });
  buyGiftMock
    .mockRejectedValueOnce(staleOrderConflict())
    .mockRejectedValueOnce(staleOrderConflict());
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await fillValidCheckout();
  fireEvent.click(screen.getByRole("button", { name: "buy" }));

  expect(await screen.findByText("order is not awaiting payment")).toBeInTheDocument();
  expect(buyGiftMock).toHaveBeenCalledTimes(2);
  expect(pushMock).not.toHaveBeenCalled();
});

it("hides the wallet tile entirely when the admin has disabled it", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  mockWallet("50000", [{ slug: "click", status: "active" }]);
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "buy" })).toBeInTheDocument();
  });
  expect(screen.queryByRole("button", { name: /payFromBalance/ })).not.toBeInTheDocument();
});

it("keeps the wallet tile visible but unselectable while it is under admin maintenance", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  mockWallet("50000", [
    { slug: "click", status: "active" },
    { slug: "wallet", status: "maintenance" },
  ]);
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  await waitFor(() => {
    expect(walletTileButton()).toBeDisabled();
  });
  // The balance (50 000, well over the 13 970 total) covers the order, but
  // the rail is closed — the caption must say so, visibly, not keep showing
  // the balance as if it were payable, and not hide the state behind a
  // `title=` tooltip.
  expect(walletTileButton()).not.toHaveAttribute("title");
  expect(walletTileButton()).toHaveTextContent("paymentMaintenance");
  expect(walletTileButton()).not.toHaveTextContent(priceText(50000));
});

it("never lets a providerStatus fetch that resolves after a wallet pick swap it back to a card", async () => {
  useAuthMock.mockReturnValue({ user: makeUser(), isLoading: false });
  setTokens("test-access-token");
  let resolveProviders: (value: {
    providers: { slug: string; status: "active" | "maintenance" }[];
  }) => void = () => {
    throw new Error("resolveProviders called before it was assigned");
  };
  const providersPromise = new Promise<{
    providers: { slug: string; status: "active" | "maintenance" }[];
  }>((resolve) => {
    resolveProviders = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url.includes("/wallet")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              balances: [
                { account_id: "acc-1", kind: "user_wallet", currency: "UZS", balance: "50000" },
              ],
            }),
        });
      }
      return providersPromise.then((body) => ({ json: () => Promise.resolve(body) }));
    }),
  );

  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  // `providerStatus` is still `null` here — `methodVisibility` fails open, so
  // the wallet tile is already selectable once the balance loads, before the
  // provider fetch ever resolves.
  await waitFor(() => {
    expect(walletTileButton()).not.toBeDisabled();
  });
  fireEvent.click(walletTileButton());
  expect(walletTileButton()).toHaveAttribute("aria-pressed", "true");

  resolveProviders({
    providers: [
      { slug: "click", status: "active" },
      { slug: "wallet", status: "active" },
    ],
  });

  // The reselect effect runs off this fetch landing — give it a tick, then
  // confirm the wallet is still the selection instead of having been swapped
  // for the first active acquirer.
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).toHaveAttribute("aria-pressed", "false");
  });
  expect(walletTileButton()).toHaveAttribute("aria-pressed", "true");
});
