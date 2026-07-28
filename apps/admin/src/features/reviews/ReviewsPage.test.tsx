import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { ReviewsPage } from "./ReviewsPage";

import type { AdminReviewList } from "./types";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

const LIST: AdminReviewList = {
  items: [
    {
      id: "rev-1",
      brand_id: "brand-aaaa1111",
      user_id: "user-bbbb2222",
      order_id: "order-cccc3333",
      rating: 5,
      body: "Отличный сервис",
      status: "published",
      report_count: 2,
      created_at: "2026-07-01T08:00:00Z",
    },
  ],
  total: 1,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReviewsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiPost.mockResolvedValue(undefined);
});

it("renders a review row with rating, body and report count", async () => {
  mockedApiGet.mockResolvedValue(LIST);
  renderPage();
  expect(await screen.findByText("Отличный сервис")).toBeInTheDocument();
  expect(screen.getByText("★★★★★")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
});

it("hides a published review via the moderation endpoint", async () => {
  mockedApiGet.mockResolvedValue(LIST);
  renderPage();
  const hideBtn = await screen.findByText("Скрыть");
  fireEvent.click(hideBtn);
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/reviews/rev-1/hide",
      {},
      expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
    );
  });
});
