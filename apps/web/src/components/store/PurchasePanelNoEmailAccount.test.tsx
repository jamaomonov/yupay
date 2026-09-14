// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

/**
 * A signed-in buyer with no address on file can still buy.
 *
 * `canPay` read `(user !== null || emailOk)`, so for anyone signed in the
 * address was never validated — and the body sent `delivery_email: ""`, which
 * the server rejects as not an address. The order failed with a 422 the buyer
 * read as «Buyurtma yaratilmadi», and there was nothing they could do about
 * it: the field seeds from the account, and 410 of 606 accounts on prod have
 * no email because they signed in through Telegram or Steam.
 *
 * Measured on prod: web checkout failed 36 times on 09-13 against 61 orders,
 * where the month before ran at about one in ten. The mini app, which does not
 * send the field at all, never failed once.
 *
 * Its own file because `useAuth` is mocked per module — the sibling suite needs
 * an account that has an address.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

// Checkout pushes the buyer to the order page (see `PurchasePanel.test.tsx`);
// without a router in scope the panel cannot render at all.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    // Telegram and Steam hand us no address. This is the majority of prod.
    user: { id: "u-1", email: null, delivery_email: null },
    isLoading: false,
  }),
}));

vi.mock("@/lib/client", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getAccessToken: () => "token",
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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
        display_price: { amount: "125000", currency: "UZS", source: "fx" },
      },
    ],
  };
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PurchasePanel products={[makeProduct()]} locale="ru" />
    </QueryClientProvider>,
  );
}

/** Captures the order POST body; everything else answers blandly. */
function stubApi(): { body: Record<string, unknown> | null } {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes("/payments/providers")) {
        return Promise.resolve(
          new Response(JSON.stringify({ providers: [{ slug: "click", status: "active" }] }), {
            status: 200,
          }),
        );
      }
      if (url.includes("/api/v1/orders") && init?.method === "POST") {
        captured.body = JSON.parse(init.body as string) as Record<string, unknown>;
        return Promise.resolve(new Response(JSON.stringify({ id: "order-1" }), { status: 200 }));
      }
      if (url.includes("/payments/intents")) {
        return Promise.resolve(new Response(JSON.stringify({ intent_url: null }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    },
  );
  return captured;
}

it("lets an account with no address on file pay, and mails the codes nowhere", async () => {
  const captured = stubApi();
  renderPanel();

  const field = await screen.findByPlaceholderText("emailPlaceholder");
  expect(field).toHaveValue("");

  fireEvent.click(await screen.findByRole("button", { name: /\$10/ }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /^pay ·/i }));
  fireEvent.click(await screen.findByRole("button", { name: "confirmCta" }));

  await waitFor(() => {
    expect(captured.body).not.toBeNull();
  });
  // Absent, not empty: "" is not an address and the server refuses the whole
  // order over it. An absent key means "mail it nowhere", which is the truth.
  expect(captured.body).not.toHaveProperty("delivery_email");
  expect(captured.body).not.toHaveProperty("guest_email");
});

it("refuses to pay with a half-typed address rather than letting the server 422", async () => {
  stubApi();
  renderPanel();

  const field = await screen.findByPlaceholderText("emailPlaceholder");
  fireEvent.change(field, { target: { value: "not-an-address" } });

  fireEvent.click(await screen.findByRole("button", { name: /\$10/ }));

  // Blank is a choice; malformed is a mistake, and the button says which.
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).toBeDisabled();
  });
  // Said twice on purpose: once under the button, once at the field itself.
  expect(screen.getAllByText("payHintEmail").length).toBeGreaterThan(0);
});
