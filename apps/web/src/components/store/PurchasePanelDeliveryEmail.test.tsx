// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

/**
 * Where a signed-in buyer's codes are sent.
 *
 * Checkout has always shown the same required email field to everyone, and for
 * a signed-in customer it dropped what they typed: the body sent
 * `guest_email` only when signed out, and nothing at all when signed in. So
 * they were asked for an address, gave one, and received no mail — on prod,
 * 107 delivered orders.
 *
 * Its own file because `useAuth` is mocked per module and the sibling suites
 * need a guest.
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
    user: { id: "u-1", email: "login@example.com", delivery_email: null },
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

it("prefills the email field from the signed-in account", async () => {
  stubApi();
  renderPanel();
  const field = await screen.findByPlaceholderText("emailPlaceholder");
  await waitFor(() => {
    expect(field).toHaveValue("login@example.com");
  });
});

it("sends where a signed-in buyer asked for their codes", async () => {
  const captured = stubApi();
  renderPanel();

  const field = await screen.findByPlaceholderText("emailPlaceholder");
  await waitFor(() => {
    expect(field).toHaveValue("login@example.com");
  });
  // Editable: one order going somewhere else is a normal thing to want.
  fireEvent.change(field, { target: { value: "elsewhere@example.com" } });

  fireEvent.click(await screen.findByRole("button", { name: /\$10/ }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /^pay ·/i }));
  fireEvent.click(await screen.findByRole("button", { name: "confirmCta" }));

  await waitFor(() => {
    expect(captured.body).not.toBeNull();
  });
  expect(captured.body?.delivery_email).toBe("elsewhere@example.com");
  // `guest_email` is the guest's claim on the order and must not be set here.
  expect(captured.body).not.toHaveProperty("guest_email");
});
