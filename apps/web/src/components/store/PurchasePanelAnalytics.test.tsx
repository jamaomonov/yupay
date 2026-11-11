// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

vi.mock("next-intl", () => ({ useTranslations: () => (k: string) => k }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const EMAIL = "buyer@example.com";

function product(): ProductDetail {
  const sku = {
    region: null,
    image_url: null,
    price_usd: "10.00",
    display_price: { amount: "125000", currency: "UZS", source: "fx" as const },
  };
  return {
    id: "prod-1",
    slug: "pubg-uc",
    brand_slug: "pubg-mobile",
    category_slug: "games",
    name: "UC",
    short_description: null,
    image_url: null,
    kind: "top_up",
    starting_price_usd: "10.00",
    starting_display_price: null,
    brand: {
      id: "brand-1",
      slug: "pubg-mobile",
      category_slug: "games",
      name: "PUBG Mobile",
      short_description: null,
      logo_url: null,
      hero_image_url: null,
      accent_color: null,
      maintenance: false,
    },
    description: null,
    required_fields: [],
    skus: [
      { ...sku, id: "sku-60", sku_code: "PUBG-60", denomination: "60 UC" },
      { ...sku, id: "sku-325", sku_code: "PUBG-325", denomination: "325 UC" },
    ],
  };
}

const ORDER = {
  id: "order-1",
  status: "awaiting_payment",
  currency: "UZS",
  total_usd: "10.00",
  total_charged: "125000",
  payment_provider: null,
  fx_snapshot_id: null,
  expires_at: "2026-11-11T12:10:00Z",
  created_at: "2026-11-11T12:00:00Z",
  paid_at: null,
  fulfilled_at: null,
  delivered_at: null,
  cancelled_at: null,
  items: [
    {
      id: "line-1",
      sku_id: "sku-60",
      qty: 1,
      unit_price_usd: "10.00",
      fulfillment_state: "pending",
      fulfillment_data: {},
      display: { brand_slug: "pubg-mobile", product_name: "UC", sku_code: "PUBG-60" },
    },
  ],
  access_token: "order-token",
};

function respond(body: unknown): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

beforeEach(() => {
  delete window.dataLayer;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("/payments/providers")) {
      return respond({ providers: [{ slug: "click", status: "active" }] });
    }
    if (url.includes("/auth/guest")) return respond({ access_token: "guest-token" });
    if (url.includes("/api/v1/orders") && init?.method === "POST") return respond(ORDER);
    if (url.includes("/payments/intents")) return respond({ intent_url: "https://pay.example" });
    return respond({});
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const named = (name: string): unknown[] =>
  (window.dataLayer ?? []).filter(
    (e) => typeof e === "object" && e !== null && "event" in e && e.event === name,
  );

it("sends select_item per new pack and the checkout pair once per order, without PII", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PurchasePanel products={[product()]} locale="ru" />
    </QueryClientProvider>,
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.click(screen.getByRole("button", { name: /^60 UC\b/ }));
  // A tap on the pack already in the cart is not a new selection.
  fireEvent.click(screen.getByRole("button", { name: /^60 UC\b/ }));
  expect(named("select_item")).toEqual([
    {
      event: "select_item",
      ecommerce: {
        currency: "UZS",
        value: 125000,
        items: [
          {
            item_id: "PUBG-60",
            item_name: "UC",
            item_brand: "pubg-mobile",
            item_variant: "60 UC",
            quantity: 1,
            price: 125000,
          },
        ],
      },
    },
  ]);

  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), { target: { value: EMAIL } });
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /^pay ·/i }));
  fireEvent.click(await screen.findByRole("button", { name: "confirmCta" }));

  await waitFor(() => {
    expect(named("add_payment_info")).toHaveLength(1);
  });
  expect(named("begin_checkout")).toEqual([
    {
      event: "begin_checkout",
      ecommerce: {
        currency: "UZS",
        value: 125000,
        items: [
          {
            item_id: "PUBG-60",
            item_name: "UC",
            item_brand: "pubg-mobile",
            price: 125000,
            quantity: 1,
          },
        ],
      },
    },
  ]);
  expect(named("add_payment_info")[0]).toMatchObject({
    ecommerce: { payment_type: "click", value: 125000, currency: "UZS" },
  });
  const all = JSON.stringify(window.dataLayer);
  expect(all).not.toContain(EMAIL);
  expect(all).not.toContain("order-token");
});
