// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

import { formatUzs } from "@/lib/seo";

/**
 * The signed-in half of the "pay from balance" tile.
 *
 * Its own file because `useAuth` is mocked per module and the sibling suite
 * needs a guest — a shared mutable mock would make each test depend on the
 * order the others ran in.
 *
 * The order here costs 1 250 000 soum (`display_price.amount` on the only
 * SKU), so the two cases are a balance above and below that.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: "u-1", email: "a@b.c" }, isLoading: false }),
}));

vi.mock("@/lib/client", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getAccessToken: () => "token",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ORDER_TOTAL = 1_250_000;

function makeProduct(): ProductDetail {
  return {
    id: "prod-1",
    slug: "steam",
    brand_slug: "steam",
    category_slug: "wallets",
    name: "Steam Wallet",
    short_description: null,
    image_url: null,
    kind: "top_up",
    starting_price_usd: "10.00",
    starting_display_price: null,
    brand: {
      id: "brand-1",
      slug: "steam",
      category_slug: "wallets",
      name: "Steam",
      short_description: null,
      logo_url: null,
      hero_image_url: null,
      accent_color: null,
      maintenance: false,
    },
    description: null,
    required_fields: [],
    skus: [
      {
        id: "sku-1",
        sku_code: "STEAM-10",
        denomination: "$10",
        region: null,
        image_url: null,
        price_usd: "10.00",
        display_price: { amount: String(ORDER_TOTAL), currency: "UZS", source: "fx" },
      },
    ],
  };
}

/** Serves the wallet balance and the provider list from one stub. */
function mockApi(balance: string): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/wallet")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              balances: [{ account_id: "acc-1", kind: "user_wallet", currency: "UZS", balance }],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ providers: [{ slug: "click", status: "active" }] }),
      });
    }),
  );
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PurchasePanel products={[makeProduct()]} locale="ru" />
    </QueryClientProvider>,
  );
}

it("offers the balance when it covers the order", async () => {
  mockApi("2000000.000000");
  renderPanel();

  const tile = await screen.findByRole("button", { name: /payFromBalance/ });
  await waitFor(() => {
    expect(tile).not.toBeDisabled();
  });
  // The amount, not a status line — there is nothing to warn about.
  expect(tile).not.toHaveTextContent("payFromBalanceShort");
  expect(tile).not.toHaveTextContent("payFromBalanceGuest");
});

it("refuses and says how much is missing when the balance is short", async () => {
  mockApi("12500.000000");
  renderPanel();

  const tile = await screen.findByRole("button", { name: /payFromBalance/ });
  await waitFor(() => {
    expect(tile).toBeDisabled();
  });
  // Disabled alone would leave the customer guessing; the shortfall is the
  // one number that tells them what to do about it.
  expect(tile).toHaveTextContent("payFromBalanceShort");
  // Formatted the way the page shows it — asserting on bare digits would
  // pass while the customer saw an unformatted number.
  expect(tile.textContent).toContain(formatUzs("ru", ORDER_TOTAL - 12500));
});
