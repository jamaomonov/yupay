// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { GiftPurchasePanel } from "./GiftPurchasePanel";

import type { Me } from "@/lib/auth";
import type * as GiftCheckoutModule from "@/lib/gift-checkout";
import type * as GiftsModule from "@/lib/gifts";
import type { GiftAppDetail, GiftPackage, GiftProfileCheck, GiftRegion } from "@/lib/gifts";

import { ApiError, clearTokens, setTokens } from "@/lib/client";
import { buyGift, GiftPriceChangedError } from "@/lib/gift-checkout";
import { checkGiftProfile } from "@/lib/gifts";
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

// Only the network call is stubbed — `profileCheckBlocks` stays the real
// predicate, so what these tests exercise is the panel's actual Buy gating
// rather than a re-declaration of it.
vi.mock("@/lib/gifts", async (importOriginal) => ({
  ...(await importOriginal<typeof GiftsModule>()),
  checkGiftProfile: vi.fn(),
}));

const buyGiftMock = vi.mocked(buyGift);
const checkGiftProfileMock = vi.mocked(checkGiftProfile);

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

// jsdom ships no layout engine, so it has no `scrollIntoView` — the mobile
// sticky bar's ghost button calls it to bring the form into view. Same
// pattern `OrderStatus.test.tsx` uses for the identical gap. Kept as its own
// named mock (not referenced via `Element.prototype.scrollIntoView` at the
// call site) so assertions never touch an unbound prototype method.
const scrollIntoViewMock = vi.fn();
beforeAll(() => {
  Element.prototype.scrollIntoView = scrollIntoViewMock;
});

afterEach(() => {
  vi.unstubAllGlobals();
  buyGiftMock.mockReset();
  checkGiftProfileMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
  toastInfoMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: null, isLoading: false });
  useLoginModal.setState({ isOpen: false });
  clearTokens();
  scrollIntoViewMock.mockClear();
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

/** Prices five distinct zones, none of them CIS (the default country UZ's
 *  zone) — `TR` listed first so `selectPackage`'s third fallback step (a
 *  country covering the package's own first priced zone) lands the buyer on
 *  it specifically. Paired with `SIX_COUNTRY_REGIONS` below, `TR` sits
 *  beyond `VISIBLE_COUNTRY_COUNT` purely by array position among the priced
 *  countries — proving the overflow auto-expands on the reassignment, not
 *  just when the lone priced country happens to fall into it. */
const TR_DELUXE_EDITION: GiftPackage = {
  id: 5,
  name: "Turkey Deluxe Edition",
  image: null,
  discount_percent: null,
  prices: [
    { zone: "TR", price_usd: "2.00", price_uzs: "25000" },
    { zone: "KZ", price_usd: "1.90", price_uzs: "24000" },
    { zone: "BY", price_usd: "1.80", price_uzs: "23000" },
    { zone: "AM", price_usd: "1.70", price_uzs: "22000" },
    { zone: "GE", price_usd: "1.60", price_uzs: "21000" },
  ],
};

/** Six countries, one priced zone each (bar UZ/CIS) — enough that a package
 *  pricing all five non-default zones still leaves more than
 *  `VISIBLE_COUNTRY_COUNT` (4) countries priced, so the fifth one overflows
 *  by position alone. */
const SIX_COUNTRY_REGIONS: GiftRegion[] = [
  { country: "UZ", zone: "CIS", price_usd: "1.10", price_uzs: "13970" },
  { country: "KZ", zone: "KZ", price_usd: "1.90", price_uzs: "24000" },
  { country: "BY", zone: "BY", price_usd: "1.80", price_uzs: "23000" },
  { country: "AM", zone: "AM", price_usd: "1.70", price_uzs: "22000" },
  { country: "GE", zone: "GE", price_usd: "1.60", price_uzs: "21000" },
  { country: "TR", zone: "TR", price_usd: "2.00", price_uzs: "25000" },
];

/** Prices only the `TR` zone — pairs with `MULTI_KEEP_TR_EDITION` below to
 *  reproduce the region-overflow path a `country`-keyed effect can't see:
 *  switching TO the multi edition keeps `country` at "TR" unchanged (its
 *  zone is still priced — `selectPackage`'s *first* branch), but the switch
 *  also newly prices four countries that sit *earlier* than TR in
 *  `SIX_COUNTRY_REGIONS`'s array order, pushing the untouched "TR"
 *  selection from a visible slot into the overflow purely by position
 *  (2026-09-04 review, round 2). */
const TR_ONLY_STANDALONE_EDITION: GiftPackage = {
  id: 6,
  name: "Turkey Only Edition",
  image: null,
  discount_percent: null,
  prices: [{ zone: "TR", price_usd: "2.00", price_uzs: "25000" }],
};

/** Prices CIS (UZ), KZ, BY, AM and TR — exactly the four countries ahead of
 *  TR in `SIX_COUNTRY_REGIONS`, plus TR itself, so TR lands at index 4 among
 *  this package's priced countries (one past `VISIBLE_COUNTRY_COUNT`). */
const MULTI_KEEP_TR_EDITION: GiftPackage = {
  id: 7,
  name: "Multi Region Keep Edition",
  image: null,
  discount_percent: null,
  prices: [
    { zone: "CIS", price_usd: "1.10", price_uzs: "13970" },
    { zone: "KZ", price_usd: "1.90", price_uzs: "24000" },
    { zone: "BY", price_usd: "1.80", price_uzs: "23000" },
    { zone: "AM", price_usd: "1.70", price_uzs: "22000" },
    { zone: "TR", price_usd: "2.00", price_uzs: "25000" },
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

/** The Buy button's accessible name — its own label — now changes with
 *  state (the missing-step reason while disabled, "buy · <amount>" once
 *  payable), so tests locate it by a stable `data-testid` instead of a role
 *  query pinned to one literal name. */
function buyButton() {
  return screen.getByTestId("gift-buy-cta");
}

/** Clicking Buy only opens `ConfirmPurchaseModal` now (2026-09-04 review) —
 *  this drives both steps, the way a real buyer would. */
function submitBuy(): void {
  fireEvent.click(buyButton());
  fireEvent.click(screen.getByRole("button", { name: "confirmCta" }));
}

async function fillValidCheckout(): Promise<void> {
  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "guest@example.com" },
  });
  await waitFor(() => {
    expect(buyButton()).not.toBeDisabled();
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

it("folds an unpriced country into the overflow and names the reason once for the whole row", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: "13970" }] },
    ],
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  // RU has no price for this package — it used to sit right in the visible
  // row, disabled, with its own "нет цены…" caption; it's now folded into
  // the overflow instead (2026-09-04 review).
  expect(screen.queryByRole("button", { name: countryButtonName("RU") })).not.toBeInTheDocument();
  expect(screen.getByText("noPriceInRegion")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "otherRegion" }));
  const ruButton = screen.getByRole("button", { name: countryButtonName("RU") });
  expect(ruButton).toBeDisabled();
  // Visible text, not a `title=` tooltip (invisible on mobile) — see
  // `CountryButton` in `GiftPurchasePanel.tsx`.
  expect(ruButton).not.toHaveAttribute("title");
  // Still exactly once — not repeated under the now-visible disabled pill.
  expect(screen.getAllByText("noPriceInRegion")).toHaveLength(1);
});

it("renders the coming-soon state instead of crashing when the API predates `regions`", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetailWithoutRegions()} skuId="sku-1" locale="ru" />);

  expect(screen.getByText("comingSoon")).toBeInTheDocument();
  expect(screen.queryByTestId("gift-buy-cta")).not.toBeInTheDocument();
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
  // RU no longer prices this edition — folded into the overflow rather
  // than shown inactive in the visible row.
  expect(screen.queryByRole("button", { name: countryButtonName("RU") })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "otherRegion" }));
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
  // UZ no longer prices this edition at all — folded into the overflow
  // rather than shown active or inactive in the visible row.
  expect(screen.queryByRole("button", { name: countryButtonName("UZ") })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "otherRegion" }));
  expect(screen.getByRole("button", { name: countryButtonName("UZ") })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(screen.getAllByText(priceText(12065)).length).toBeGreaterThan(0);
});

/**
 * The region-overflow bug: `countryExpanded` used to come from a `useState`
 * initializer only — checked once, at mount. `selectPackage` can move the
 * buyer's country into the overflow well after that (here: a package
 * switch whose fallback lands on a country five *priced* countries deep,
 * beyond `VISIBLE_COUNTRY_COUNT`), and without re-deriving on every
 * `country` change, that pill stayed hidden behind "другой регион" with no
 * visible sign it was even selected (2026-09-04 review).
 */
it("expands the region overflow when a package switch reassigns the country into it", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [STANDARD_EDITION, TR_DELUXE_EDITION],
    regions: SIX_COUNTRY_REGIONS,
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  // Not expanded yet — the default country (UZ) is visible on its own.
  expect(screen.queryByRole("button", { name: countryButtonName("TR") })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Turkey Deluxe Edition/ }));

  // TR is the country the fallback lands on, and it sits fifth among this
  // package's priced countries — beyond the four visible slots. It must be
  // visible and marked selected without an extra click on "другой регион".
  expect(screen.getByRole("button", { name: countryButtonName("TR") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

/**
 * The path a `country`-keyed `useEffect` can't see: `selectPackage`'s
 * *first* branch deliberately leaves `country` unchanged whenever the new
 * package still prices its zone — but that same switch can still reorder
 * `pricedCountries`, pushing the untouched selection out of the visible
 * slice. An effect that only re-fires when `country` itself changes never
 * runs here, so `countryExpanded` stays stale and the selected country ends
 * up hidden behind "другой регион" with nothing highlighted (2026-09-04
 * review, round 2) — this is exactly why the expand is derived at render
 * (`countryPanelExpanded`) instead of synced through an effect.
 */
it("keeps the still-selected country visible when a switch reorders it into the overflow without `country` itself changing", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [TR_ONLY_STANDALONE_EDITION, MULTI_KEEP_TR_EDITION],
    regions: SIX_COUNTRY_REGIONS,
    region_default: "TR",
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  // TR starts out selected and visible — the only priced country under the
  // first package.
  expect(screen.getByRole("button", { name: countryButtonName("TR") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  fireEvent.click(screen.getByRole("button", { name: /Multi Region Keep Edition/ }));

  // The new package still prices TR's own zone, so `selectPackage`'s first
  // branch keeps `country` at "TR" — `country` never changes. But the same
  // switch newly prices four countries ahead of TR in the regions array,
  // pushing TR past the four visible slots. It must still be visible and
  // marked selected, not silently stranded behind the toggle.
  expect(screen.getByRole("button", { name: countryButtonName("TR") })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
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

  // Now shown in three places at once: the FX-down price card, the Buy
  // button's own disabled label, and the mobile sticky bar's reason line —
  // all three name the same blocker (2026-09-04 review).
  expect(screen.getAllByText("priceUnavailable").length).toBeGreaterThan(0);

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
  });
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "guest@example.com" },
  });
  // Never enabled — a valid invite and email are not enough while FX is down.
  expect(buyButton()).toBeDisabled();
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

it("blocks submit on a bad invite URL, and shows the i18n error once the field is left", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const inviteInput = screen.getByLabelText("inviteLabel");
  fireEvent.change(inviteInput, { target: { value: "https://example.com/not-steam" } });

  // Not yet — it used to fire on the very first keystroke, before the buyer
  // had even finished typing (2026-09-04 review). Buy is already blocked,
  // though: the gate itself is immediate, only the visible error is timed.
  expect(screen.queryByText("inviteError")).not.toBeInTheDocument();
  expect(buyButton()).toBeDisabled();
  expect(buyGiftMock).not.toHaveBeenCalled();

  fireEvent.blur(inviteInput);
  expect(screen.getByText("inviteError")).toBeInTheDocument();
  expect(buyButton()).toBeDisabled();
});

it("shows the invite error after an idle pause even without a blur", async () => {
  vi.useFakeTimers();
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  fireEvent.change(screen.getByLabelText("inviteLabel"), {
    target: { value: "https://example.com/not-steam" },
  });
  expect(screen.queryByText("inviteError")).not.toBeInTheDocument();

  await vi.advanceTimersByTimeAsync(700);
  vi.useRealTimers();

  expect(screen.getByText("inviteError")).toBeInTheDocument();
});

it("announces the invite error via aria-invalid/aria-describedby, not just a floating paragraph", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  const inviteInput = screen.getByLabelText("inviteLabel");
  fireEvent.change(inviteInput, { target: { value: "https://example.com/not-steam" } });
  fireEvent.blur(inviteInput);

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
  expect(buyButton()).toBeDisabled();
});

/**
 * The Buy button used to always read "Купить" and just grey out — no hint
 * why. It now carries the amount once payable, and names the next required
 * step, in the same order `canBuy` itself checks, while it isn't
 * (2026-09-04 review, "ship this first").
 */
describe("the Buy button carries the amount, or names the missing step", () => {
  it("names the invite field when it's still empty", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    expect(buyButton()).toHaveTextContent("payHintInvite");
  });

  it("names the invite link as wrong once it doesn't parse as one", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    fireEvent.change(screen.getByLabelText("inviteLabel"), {
      target: { value: "https://example.com/not-steam" },
    });
    expect(buyButton()).toHaveTextContent("payHintInviteInvalid");
  });

  it("asks a guest for their email once the invite is valid", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    fireEvent.change(screen.getByLabelText("inviteLabel"), {
      target: { value: "https://steamcommunity.com/profiles/76561198000000000" },
    });
    expect(buyButton()).toHaveTextContent("payHintEmail");
  });

  it('reads "buy · <amount>" once every field is filled', async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    expect(buyButton()).toHaveTextContent(`buy · ${priceText(13970)}`);
  });
});

it("shows one inline line covering the self-purchase case, next to the invite field", () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  expect(screen.getByText("inviteSelfNote")).toBeInTheDocument();
});

it('drops "inviteGuideTitle" — it only restated the field label right above it', () => {
  mockProvidersResponse();
  renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

  expect(screen.queryByText("inviteGuideTitle")).not.toBeInTheDocument();
});

describe('the "Открыть профиль" link', () => {
  it("is absent until the invite link is valid", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    expect(screen.queryByRole("link", { name: /openProfileLink/ })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("inviteLabel"), {
      target: { value: "not-a-link" },
    });
    expect(screen.queryByRole("link", { name: /openProfileLink/ })).not.toBeInTheDocument();
  });

  it("opens the pasted link, normalized, in a new tab once it's valid", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    fireEvent.change(screen.getByLabelText("inviteLabel"), {
      target: { value: "https://steamcommunity.com/id/somebuyer" },
    });
    const link = screen.getByRole("link", { name: /openProfileLink/ });
    expect(link).toHaveAttribute("href", "https://steamcommunity.com/id/somebuyer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("defaults a schemeless paste to https:// for the link too", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    fireEvent.change(screen.getByLabelText("inviteLabel"), {
      target: { value: "steamcommunity.com/id/somebuyer" },
    });
    expect(screen.getByRole("link", { name: /openProfileLink/ })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/id/somebuyer",
    );
  });
});

it("announces a price change via aria-live, not silently", () => {
  mockProvidersResponse();
  const { container } = renderPanel(
    <GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />,
  );

  const liveRegion = container.querySelector('[aria-live="polite"]');
  expect(liveRegion).not.toBeNull();
  expect(liveRegion).toHaveTextContent(priceText(13970));
});

it("gives an unpriced edition's price real text for a screen reader, not a bare dash", () => {
  mockProvidersResponse();
  const detail = makeDetail({
    packages: [
      { ...STANDARD_EDITION, prices: [{ zone: "CIS", price_usd: "1.10", price_uzs: null }] },
    ],
  });
  renderPanel(<GiftPurchasePanel detail={detail} skuId="sku-1" locale="ru" />);

  const editionButton = screen.getByRole("button", { name: /Standard Edition/ });
  expect(editionButton).toHaveTextContent("—");
  expect(editionButton).toHaveTextContent("noPriceInRegion");
});

describe("the confirm dialog", () => {
  it("opens on Buy instead of charging immediately, with edition/region/profile/total", async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    fireEvent.click(buyButton());

    expect(buyGiftMock).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Standard Edition");
    expect(dialog).toHaveTextContent(countryName("UZ", "ru"));
    expect(dialog).toHaveTextContent("https://steamcommunity.com/profiles/76561198000000000");
    expect(dialog).toHaveTextContent(priceText(13970));
  });

  it("never charges when the buyer cancels out of the confirm dialog", async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    fireEvent.click(buyButton());
    fireEvent.click(screen.getByRole("button", { name: "confirmCancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(buyGiftMock).not.toHaveBeenCalled();
  });

  it("charges only after the buyer confirms", async () => {
    mockProvidersResponse();
    buyGiftMock.mockResolvedValue({
      orderId: "order-1",
      intentUrl: null,
      trackHref: "/orders/order-1?email=guest%40example.com",
    });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    submitBuy();

    await waitFor(() => {
      expect(buyGiftMock).toHaveBeenCalledTimes(1);
    });
  });
});

/**
 * The gift page had no mobile sticky checkout bar at all (2026-09-04
 * review) — this is a brand-new interactive surface with its own testid,
 * its own disabled/ghost-vs-primary branching (mirrors the main CTA's
 * `canBuy`, but the DOM `disabled` attribute isn't how it expresses that —
 * see `PurchasePanel.test.tsx`'s identical note on its own sticky bar) and
 * its own auto-hide `IntersectionObserver` effect.
 */
describe("the mobile sticky checkout bar", () => {
  function stickyButton() {
    return screen.getByTestId("gift-buy-sticky");
  }

  it("mirrors the main CTA's blocked state: ghost + goToPay while not payable", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    // Nothing filled in yet — neither CTA is payable.
    expect(buyButton()).toBeDisabled();
    expect(stickyButton()).toHaveTextContent("goToPay");
    // The ghost variant, not the primary lime one — `buttonStyles`'
    // `ghost` class, absent from `primary`.
    expect(stickyButton().className).toContain("border-border-2");
    expect(stickyButton().className).not.toContain("bg-primary");
  });

  it("mirrors the main CTA's payable state: primary + the amount already shown beside it", async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    expect(buyButton()).not.toBeDisabled();
    expect(stickyButton()).toHaveTextContent("buy");
    expect(stickyButton().className).toContain("bg-primary");
  });

  it("tapping it while payable opens the confirm dialog — never buyGift directly", async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    fireEvent.click(stickyButton());

    expect(buyGiftMock).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "confirmCta" }));
    await waitFor(() => {
      expect(buyGiftMock).toHaveBeenCalledTimes(1);
    });
  });

  it("tapping it while not payable scrolls to the form instead of opening the dialog", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    // Nothing filled in — not payable.
    fireEvent.click(stickyButton());

    expect(scrollIntoViewMock).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(buyGiftMock).not.toHaveBeenCalled();
  });

  it("shows the spinner, like the main CTA, while a purchase is in flight", async () => {
    mockProvidersResponse();
    // Never resolves within the test — keeps `loading` true so both CTAs
    // stay in the pending state throughout. An expression body (not an
    // empty block) so this isn't flagged as a no-op function.
    buyGiftMock.mockReturnValue(new Promise(() => undefined));
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);
    await fillValidCheckout();

    submitBuy();

    await waitFor(() => {
      expect(stickyButton().querySelector(".animate-spin")).not.toBeNull();
    });
    expect(buyButton().querySelector(".animate-spin")).not.toBeNull();
  });
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
  submitBuy();

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
  submitBuy();

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
  submitBuy();

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
  submitBuy();
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
  submitBuy();

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
  submitBuy();
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });

  submitBuy();
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
  submitBuy();
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });

  fireEvent.click(screen.getByRole("button", { name: countryButtonName("RU") }));
  submitBuy();
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
  submitBuy();
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  expect(orderKeyOf(0)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Payme" }));
  submitBuy();
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
  submitBuy();
  await waitFor(() => {
    expect(buyGiftMock).toHaveBeenCalledTimes(1);
  });
  const firstKey = orderKeyOf(0);

  // Same inputs, a second purchase after the first succeeded.
  submitBuy();
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
  submitBuy();

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
  submitBuy();

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
    expect(buyButton()).toBeInTheDocument();
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

/**
 * The pre-purchase recipient check (2026-09-04): «Проверить» resolves the
 * pasted link through `POST /gifts/steam-profile` and shows who it actually
 * points to, so a mistyped link stops being an unrecoverable, paid mistake.
 *
 * The rule every state here is written against: **only a definitive
 * `not_found` may block the purchase.** `unsupported` (an `s.team` friend
 * invite the Web API cannot resolve) and `unavailable` (no key, a Steam
 * outage, a timeout) are our failures, not the recipient's, and a check that
 * fails on our side must never cost a sale.
 */
describe("the recipient profile check", () => {
  const AVATAR = "https://avatars.steamstatic.com/abc_full.jpg";
  const FOUND: GiftProfileCheck = { status: "found", nickname: "Neo", avatarUrl: AVATAR };

  function checkButton(): HTMLElement {
    return screen.getByRole("button", { name: "check" });
  }

  function pasteInvite(url: string): void {
    fireEvent.change(screen.getByLabelText("inviteLabel"), { target: { value: url } });
  }

  it("collapses the field into a card with the recipient's nickname and avatar", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());

    expect(await screen.findByText("Neo")).toBeInTheDocument();
    // The exact src, not a substring: `/_next/image?url=https%3A%2F%2Favatars…`
    // leaves the hostname readable, so a `stringContaining` assertion would
    // pass even if the third-party host were being run through the optimizer
    // (which 504s rather than degrading — see `lib/image.ts`).
    const avatar = screen.getByTestId("gift-profile-avatar");
    expect(avatar).toHaveAttribute("src", AVATAR);
    expect(avatar.getAttribute("src")).not.toContain("/_next/image");
    expect(checkGiftProfileMock).toHaveBeenCalledWith("https://steamcommunity.com/id/neo");
    // Collapsed: the input is gone, replaced by the confirmation card.
    expect(screen.queryByLabelText("inviteLabel")).not.toBeInTheDocument();
  });

  it("keeps Buy available once the recipient is confirmed", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());

    expect(await screen.findByText("Neo")).toBeInTheDocument();
    expect(buyButton()).not.toBeDisabled();
  });

  it("blocks Buy on a definitive not_found, and the CTA says why", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "not_found" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("profileNotFound");
    expect(buyButton()).toBeDisabled();
    expect(buyButton()).toHaveTextContent("payHintProfileNotFound");
    // The field stays open on a miss — the buyer fixes the link in place.
    expect(screen.getByLabelText("inviteLabel")).toBeInTheDocument();
  });

  it("leaves Buy available on unavailable, with a neutral note", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "unavailable" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());

    expect(await screen.findByText("profileUnavailable")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(buyButton()).not.toBeDisabled();
  });

  it("leaves Buy available on an unsupported link type, with a neutral note", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "unsupported" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    pasteInvite("https://s.team/p/abc-defg");
    fireEvent.click(checkButton());

    expect(await screen.findByText("profileUnsupported")).toBeInTheDocument();
    expect(buyButton()).not.toBeDisabled();
  });

  it("resets the check — and unblocks Buy — as soon as the link is edited", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "not_found" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("profileNotFound");

    pasteInvite("https://steamcommunity.com/id/neo");

    expect(screen.queryByText("profileNotFound")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(buyButton()).not.toBeDisabled();
    });
  });

  it("reopens the field from the card, with the pasted link still in it", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());
    fireEvent.click(await screen.findByRole("button", { name: "checkEdit" }));

    expect(screen.getByLabelText("inviteLabel")).toHaveValue("https://steamcommunity.com/id/neo");
    expect(screen.queryByText("Neo")).not.toBeInTheDocument();
  });

  it("refuses to check a link that doesn't parse, and shows the link error instead", () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://example.com/not-steam");
    expect(checkButton()).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(checkButton());

    expect(checkGiftProfileMock).not.toHaveBeenCalled();
    // Pressing it answers rather than swallowing the click — same posture as
    // `CheckablePlayerField`'s `aria-disabled` button in `PurchasePanel`.
    expect(screen.getByText("inviteError")).toBeInTheDocument();
  });

  it("ignores a verdict that lands after the buyer has already changed the link", async () => {
    mockProvidersResponse();
    let resolveCheck: (v: GiftProfileCheck) => void = () => {
      throw new Error("resolveCheck called before it was assigned");
    };
    checkGiftProfileMock.mockReturnValue(
      new Promise<GiftProfileCheck>((resolve) => {
        resolveCheck = resolve;
      }),
    );
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());
    // The buyer corrects the link while the lookup for the old one is still
    // in flight; the answer that lands is about a profile they no longer mean.
    pasteInvite("https://steamcommunity.com/id/neo");
    resolveCheck({ status: "not_found" });

    await waitFor(() => {
      expect(checkButton()).toHaveTextContent("check");
    });
    expect(screen.queryByText("profileNotFound")).not.toBeInTheDocument();
    expect(buyButton()).not.toBeDisabled();
  });

  it("hands focus to «Изменить» when the field collapses out from under it", async () => {
    // The «Проверить» button unmounts with the field, so without this focus
    // lands on <body> and a keyboard user's next Tab restarts at the top of
    // the page — with nothing having announced that the check succeeded.
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "checkEdit" })).toHaveFocus();
    });
  });

  it("stops telling the buyer to fill in a field that has collapsed", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    // Before the check: both the self-purchase note and the "how to copy the
    // link" guide (its steps come from the mocked `t.raw`) are on screen,
    // because there is a field to fill in.
    expect(screen.getByText("inviteSelfNote")).toBeInTheDocument();
    expect(screen.getByText("Step one")).toBeInTheDocument();

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());
    expect(await screen.findByText("Neo")).toBeInTheDocument();

    expect(screen.queryByText("inviteSelfNote")).not.toBeInTheDocument();
    expect(screen.queryByText("Step one")).not.toBeInTheDocument();
    // What the gift *is* still applies after the recipient is confirmed —
    // only the fill-in-the-field guidance goes away.
    expect(screen.getByText("timeline")).toBeInTheDocument();
  });

  it("puts the confirmed nickname on the last screen before payment", async () => {
    // The modal's own warning tells the buyer to check the recipient; the
    // answer to that instruction was sitting in state and withheld.
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(checkButton());
    expect(await screen.findByText("Neo")).toBeInTheDocument();
    fireEvent.click(buyButton());

    expect(
      screen.getByText("Neo · https://steamcommunity.com/profiles/76561198000000000"),
    ).toBeInTheDocument();
  });

  it("falls back to the bare link in the modal when no check was run", async () => {
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    fireEvent.click(buyButton());

    expect(
      screen.getByText("https://steamcommunity.com/profiles/76561198000000000"),
    ).toBeInTheDocument();
  });

  it("says what's missing when «Проверить» is pressed on an empty field", () => {
    // `inviteWrong` requires a non-empty value, so the empty case had nothing
    // to render and the button was a silent no-op.
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    expect(screen.getByTestId("gift-profile-live")).toHaveTextContent("");
    fireEvent.click(checkButton());

    expect(checkGiftProfileMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("gift-profile-live")).toHaveTextContent("payHintInvite");
  });

  it("announces who the link resolved to, not just «Изменить»", async () => {
    // The success case is the entire reason the feature exists, and it was the
    // one verdict saying nothing: `profileNote` is null on `found`, the
    // nickname is a plain <div>, the avatar is `alt=""`, and focus lands on a
    // button whose whole accessible name is «Изменить». A screen-reader user
    // heard "Изменить, кнопка" and nothing about the recipient.
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());

    const live = screen.getByTestId("gift-profile-live");
    await waitFor(() => {
      expect(live).toHaveTextContent("profileFound");
    });
    // The nickname itself, not just a generic "found" — the point is *who*.
    expect(live).toHaveTextContent("Neo");
    // Announced only: the card already shows this visually, so the region
    // stays `sr-only` rather than repeating it on screen.
    expect(live).toHaveClass("sr-only");
  });

  it("stops re-announcing the empty-field hint once the buyer starts editing", async () => {
    // The flag behind the hint used to live for the component's lifetime, so
    // any later moment the field was empty re-showed it with no press behind
    // it — spoken mid-edit, since the region is `aria-live="polite"`.
    mockProvidersResponse();
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    fireEvent.click(checkButton());
    const live = screen.getByTestId("gift-profile-live");
    expect(live).toHaveTextContent("payHintInvite");

    pasteInvite("https://steamcommunity.com/id/neo");
    expect(live).toHaveTextContent("");

    // Select-all-and-retype: back to empty, but no press since — silent.
    pasteInvite("");
    expect(live).toHaveTextContent("");
  });

  it("keeps the live region mounted so an updated verdict is actually announced", async () => {
    // NVDA/JAWS commonly miss a `role="status"` node inserted into the page;
    // the region has to already be there and change its text. `not_found`
    // keeps its own `role="alert"`, which does announce on insertion.
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "unavailable" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    const live = screen.getByTestId("gift-profile-live");
    expect(live).toHaveAttribute("aria-live", "polite");

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());

    await waitFor(() => {
      expect(live).toHaveTextContent("profileUnavailable");
    });
    // The very same node, not a replacement one.
    expect(screen.getByTestId("gift-profile-live")).toBe(live);
  });

  // 2026-09-04 review round 1: the verdict used to be filed under the raw
  // field text, so a cosmetic edit resolving to the SAME profile discarded it
  // as stale — and Buy came back for a profile Steam had just said does not
  // exist. Harmless for the three non-blocking verdicts; not for the one that
  // is allowed to stop a purchase.
  it("holds a not_found through an edit that still means the same profile", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "not_found" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    pasteInvite("https://steamcommunity.com/id/neo/");
    fireEvent.click(checkButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("profileNotFound");

    // Same profile, three cosmetic differences: no scheme, no trailing slash.
    pasteInvite("steamcommunity.com/id/neo");

    expect(screen.getByRole("alert")).toHaveTextContent("profileNotFound");
    expect(buyButton()).toBeDisabled();
    expect(buyButton()).toHaveTextContent("payHintProfileNotFound");
  });

  it("still drops the verdict when the edit means a different profile", async () => {
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue({ status: "not_found" });
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    await fillValidCheckout();
    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("profileNotFound");

    pasteInvite("https://steamcommunity.com/id/neo2");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(buyButton()).not.toBeDisabled();
  });

  it("names the recipient even if the polite announcement is dropped", async () => {
    // The announcement and the focus move land in the same commit, and screen
    // readers commonly drop a pending polite message when focus moves. In the
    // found state the live region is referenced by no `aria-describedby` —
    // the input that carried it has just unmounted — so a dropped
    // announcement left the user with only "Изменить, кнопка" and no idea who
    // the gift was going to (2026-09-04 final review). The card's own control
    // now points at the region, so the name is part of what focusing it
    // reads, announcement or not.
    mockProvidersResponse();
    checkGiftProfileMock.mockResolvedValue(FOUND);
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    fireEvent.click(checkButton());

    const edit = await screen.findByRole("button", { name: "checkEdit" });
    const describedBy = edit.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    const description = document.getElementById(describedBy ?? "");
    expect(description).toBe(screen.getByTestId("gift-profile-live"));
    expect(description).toHaveTextContent("Neo");
  });

  it("keeps «Проверить» focusable while the check runs, and refuses the second press", async () => {
    // A real `disabled` drops focus to <body> the instant a keyboard user
    // activates the button, and only the `found` path ever re-homes it — on
    // `not_found`/`unavailable` they are left nowhere for up to the full 8 s
    // timeout (2026-09-04 review round 1). The button is `aria-busy` instead,
    // and the handler refuses the duplicate.
    mockProvidersResponse();
    let resolveCheck: (v: GiftProfileCheck) => void = () => {
      throw new Error("resolveCheck called before it was assigned");
    };
    checkGiftProfileMock.mockReturnValue(
      new Promise<GiftProfileCheck>((resolve) => {
        resolveCheck = resolve;
      }),
    );
    renderPanel(<GiftPurchasePanel detail={makeDetail()} skuId="sku-1" locale="ru" />);

    pasteInvite("https://steamcommunity.com/id/neo");
    const button = screen.getByRole("button", { name: "check" });
    button.focus();
    fireEvent.click(button);

    const busy = screen.getByRole("button", { name: "checking" });
    expect(busy).not.toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toHaveFocus();

    fireEvent.click(busy);
    expect(checkGiftProfileMock).toHaveBeenCalledTimes(1);

    resolveCheck({ status: "unavailable" });
    await waitFor(() => {
      expect(screen.getByTestId("gift-profile-live")).toHaveTextContent("profileUnavailable");
    });
    // Still where the buyer left it — the check answered without moving focus.
    expect(screen.getByRole("button", { name: "check" })).toHaveFocus();
  });
});
