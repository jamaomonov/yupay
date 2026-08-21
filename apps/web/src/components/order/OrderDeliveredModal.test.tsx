// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { OrderDeliveredModal } from "./OrderDeliveredModal";

import type * as ClientModule from "@/lib/client";
import type { OrderOut } from "@/lib/orders-types";
import type { OwnReview, Review } from "@/lib/reviews";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/client";
import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => (k: string) => `${ns}.${k}`,
  useLocale: () => "ru",
}));

const mockApiFetch = vi.fn<(path: string) => Promise<OrderOut>>();
// `ApiError` is kept real — the modal branches on `err instanceof ApiError` to
// tell "already reviewed" (409) from a transient failure.
vi.mock("@/lib/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  apiFetch: (path: string) => mockApiFetch(path),
}));

const mockGetMyReviews = vi.fn<() => Promise<{ items: OwnReview[] }>>();
const mockSubmitReview = vi.fn<(body: Record<string, unknown>) => Promise<Review>>();
vi.mock("@/lib/reviews", () => ({
  getMyReviews: () => mockGetMyReviews(),
  submitReview: (body: Record<string, unknown>) => mockSubmitReview(body),
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
          variable_amount: false,
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

/** Opens the modal on a delivered, not-yet-reviewed order and waits for it. */
async function openWithForm() {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({ items: [] });
  useOrderDeliveredModal.setState({ orderId: ORDER_ID });
  renderModal();
  return screen.findByText("web.brandReviews.formTitle");
}

// Reset in `beforeEach` only (not `afterEach`): a store update after the test
// body returns, while the component is still mounted, re-renders it outside
// React Testing Library's `act()`-wrapped cleanup/unmount.
beforeEach(() => {
  mockApiFetch.mockReset();
  mockGetMyReviews.mockReset();
  mockSubmitReview.mockReset();
  useOrderDeliveredModal.setState({ orderId: null });
});

test("renders nothing when the store is closed", () => {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({ items: [] });

  renderModal();

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("collects the review in the modal instead of linking to the brand page", async () => {
  await openWithForm();

  expect(screen.getByRole("button", { name: "web.brandReviews.submit" })).toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(mockApiFetch).toHaveBeenCalledWith(`/orders/${ORDER_ID}`);
});

test("submits the rating and comment for the delivered order", async () => {
  mockSubmitReview.mockResolvedValue({
    id: "rev-1",
    rating: 5,
    body: "быстро",
    author_name: null,
    created_at: "2026-07-28T00:00:00Z",
  });
  await openWithForm();

  fireEvent.click(screen.getByRole("button", { name: "5" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "быстро" } });
  fireEvent.click(screen.getByRole("button", { name: "web.brandReviews.submit" }));

  expect(await screen.findByText("web.brandReviews.thanks")).toBeInTheDocument();
  expect(mockSubmitReview).toHaveBeenCalledWith({
    order_id: ORDER_ID,
    brand_slug: "steam",
    rating: 5,
    body: "быстро",
  });
});

test("reports an order rated elsewhere in the meantime (409)", async () => {
  mockSubmitReview.mockRejectedValue(new ApiError(409, "/reviews"));
  await openWithForm();

  fireEvent.click(screen.getByRole("button", { name: "4" }));
  fireEvent.click(screen.getByRole("button", { name: "web.brandReviews.submit" }));

  expect(await screen.findByText("web.brandReviews.alreadyReviewed")).toBeInTheDocument();
});

test("hides the review form when the order is already reviewed", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("steam"));
  mockGetMyReviews.mockResolvedValue({
    items: [{ id: "rev-1", order_id: ORDER_ID, brand_id: "brand-1", rating: 5 }],
  });
  useOrderDeliveredModal.setState({ orderId: ORDER_ID });

  renderModal();

  await screen.findByRole("dialog");
  // The dialog can render before `my-reviews` settles, and the form only ever
  // disappears as that answer lands — so retry instead of asserting on the
  // first paint.
  await waitFor(() => {
    expect(screen.queryByText("web.brandReviews.formTitle")).not.toBeInTheDocument();
  });
  expect(
    screen.getByRole("heading", { name: "web.orderResult.deliveredTitle" }),
  ).toBeInTheDocument();
});
