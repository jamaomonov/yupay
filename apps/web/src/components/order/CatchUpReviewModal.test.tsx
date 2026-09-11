// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { CatchUpReviewModal } from "./CatchUpReviewModal";

import type { PendingAsk, Review } from "@/lib/reviews";
import type { ReactNode } from "react";

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => (k: string) => `${ns}.${k}`,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/en",
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: "u1" } }),
}));

const ASK: PendingAsk = {
  order_id: "order-catch",
  brand_slug: "steam",
  brand_name: "Steam",
  delivered_at: "2026-09-01T00:00:00Z",
};

let pending: PendingAsk | null = ASK;
const mockSubmitReview = vi.fn<(body: Record<string, unknown>) => Promise<Review>>();
const mockAmendReview =
  vi.fn<(id: string, body: string, opts?: { guestEmail?: string }) => Promise<Review>>();

vi.mock("@/lib/reviews", () => ({
  getPendingAsk: () => Promise.resolve(pending),
  submitReview: (body: Record<string, unknown>) => mockSubmitReview(body),
  amendReview: (id: string, body: string, opts?: { guestEmail?: string }) =>
    mockAmendReview(id, body, opts ?? {}),
  getMyReviews: () => Promise.resolve({ items: [] }),
}));

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return render(<CatchUpReviewModal />, { wrapper });
}

beforeEach(() => {
  pending = ASK;
  mockSubmitReview.mockReset();
  mockAmendReview.mockReset();
  window.localStorage.clear();
});

test("stays open after a star tap so the buyer can type a comment", async () => {
  mockSubmitReview.mockImplementation((body) => {
    pending = null;
    return Promise.resolve({
      id: "rev-1",
      rating: Number(body.rating),
      body: null,
      author_name: null,
      created_at: "2026-09-11T00:00:00Z",
    });
  });

  wrap();
  expect(await screen.findByRole("dialog")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "5" }));

  expect(await screen.findByText("web.brandReviews.thanksRating")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "web.brandReviews.submit" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "web.brandReviews.later" })).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "быстро дошло" } });
  fireEvent.click(screen.getByRole("button", { name: "web.brandReviews.submit" }));

  await waitFor(() => {
    expect(mockAmendReview).toHaveBeenCalledWith("rev-1", "быстро дошло", {});
  });
  expect(await screen.findByText("web.brandReviews.thanks")).toBeInTheDocument();
  expect(screen.getByText("web.brandReviews.thanksBody")).toBeInTheDocument();
});
