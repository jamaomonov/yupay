// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { OrderDeliveredModal } from "./OrderDeliveredModal";

import type { OrderOut } from "@/lib/orders-types";
import type { OwnReview } from "@/lib/reviews";
import type { ReactNode } from "react";

import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string) => `orderResult.${k}`,
  useLocale: () => "ru",
}));

const mockApiFetch = vi.fn<(path: string) => Promise<OrderOut>>();
vi.mock("@/lib/client", () => ({
  apiFetch: (path: string) => mockApiFetch(path),
}));

const mockGetMyReviews = vi.fn<() => Promise<{ items: OwnReview[] }>>();
vi.mock("@/lib/reviews", () => ({
  getMyReviews: () => mockGetMyReviews(),
}));

const ORDER_ID = "order-abc-123";

function makeOrder(brandSlug: string): OrderOut {
  return {
    id: ORDER_ID,
    status: "delivered",
    currency: "USD",
    total_usd: "10.00",
    total_charged: "10.00",
    payment_provider: null,
    fx_snapshot_id: null,
    expires_at: "2026-07-28T00:00:00Z",
    created_at: "2026-07-28T00:00:00Z",
    paid_at: "2026-07-28T00:00:00Z",
    fulfilled_at: "2026-07-28T00:00:00Z",
    delivered_at: "2026-07-28T00:00:00Z",
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 1,
        unit_price_usd: "10.00",
        fulfillment_state: "delivered",
        fulfillment_data: {},
        display: {
          brand_slug: brandSlug,
          brand_name: "Steam",
          product_slug: "steam-wallet",
          product_name: "Steam Wallet",
          product_kind: "topup",
          sku_code: "STEAM-10",
          denomination: "$10",
          region: null,
          image_url: null,
        },
      },
    ],
  };
}

function renderModal() {
  const qc = new QueryClient();
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return render(<OrderDeliveredModal />, { wrapper });
}

// Reset in `beforeEach` only (not `afterEach`): a store update after the test
// body returns, while the component is still mounted, re-renders it outside
// React Testing Library's `act()`-wrapped cleanup/unmount.
beforeEach(() => {
  mockApiFetch.mockReset();
  mockGetMyReviews.mockReset();
  useOrderDeliveredModal.setState({ orderId: null });
});

test("renders nothing when the store is closed", () => {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({ items: [] });

  renderModal();

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("shows the rate CTA linking to the brand review anchor when not yet reviewed", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({ items: [] });
  useOrderDeliveredModal.setState({ orderId: ORDER_ID });

  renderModal();

  const cta = await screen.findByRole("link", { name: "orderResult.rateCta" });
  // ru is the default locale → canonical, prefix-less path (pathFor).
  expect(cta).toHaveAttribute("href", `/store/steam?order=${ORDER_ID}#reviews`);
  expect(mockApiFetch).toHaveBeenCalledWith(`/orders/${ORDER_ID}`);
});

test("hides the rate CTA when the order is already reviewed", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({
    items: [{ id: "rev-1", order_id: ORDER_ID, brand_id: "brand-1", rating: 5 }],
  });
  useOrderDeliveredModal.setState({ orderId: ORDER_ID });

  renderModal();

  await screen.findByRole("dialog");
  expect(screen.queryByRole("link", { name: "orderResult.rateCta" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "orderResult.deliveredTitle" })).toBeInTheDocument();
});
