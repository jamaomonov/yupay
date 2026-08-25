import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { ReviewsPage } from "./ReviewsPage";

import type { AdminBrandReviewStatsList, AdminReviewList } from "./types";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  // The page reads the error text through `extractApiMessage`, which narrows on
  // `ApiError`; without it here the error branch throws instead of rendering.
  ApiError: class ApiError extends Error {},
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
      brand_slug: "roblox",
      brand_name: "Roblox",
      brand_logo_url: "https://cdn.example/roblox.png",
      user_name: "Дарья",
      guest_email: null,
    },
    {
      id: "rev-2",
      brand_id: "brand-aaaa1111",
      user_id: null,
      order_id: "order-dddd4444",
      rating: 3,
      body: null,
      status: "published",
      report_count: 0,
      created_at: "2026-07-02T08:00:00Z",
      brand_slug: "roblox",
      brand_name: "Roblox",
      brand_logo_url: "https://cdn.example/roblox.png",
      user_name: null,
      guest_email: "guest@example.com",
    },
  ],
  // Larger than one page, so the pager renders and its counts are checked.
  total: 45,
};

const BY_BRAND: AdminBrandReviewStatsList = {
  items: [
    {
      brand_slug: "roblox",
      brand_name: "Roblox",
      brand_logo_url: "https://cdn.example/roblox.png",
      total: 2,
      avg_rating: 4,
      reported: 1,
    },
  ],
};

/** Both blocks fetch; route by URL so each gets its own shape. */
function mockApi(list: AdminReviewList = LIST): void {
  mockedApiGet.mockImplementation((path: string) =>
    Promise.resolve(path.includes("by-brand") ? BY_BRAND : list),
  );
}

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
  mockApi();
  renderPage();
  expect(await screen.findByText("Отличный сервис")).toBeInTheDocument();
  expect(screen.getByText("★★★★★")).toBeInTheDocument();
  expect(screen.getByText(/2 жалобы/)).toBeInTheDocument();
});

it("hides a published review via the moderation endpoint", async () => {
  mockApi();
  renderPage();
  // Two rows, so two Hide buttons — the first belongs to rev-1.
  const hideBtn = (await screen.findAllByText("Скрыть"))[0]!;
  fireEvent.click(hideBtn);
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/reviews/rev-1/hide",
      {},
      expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
    );
  });
});

it("shows an error state with Retry — never the empty state — when the fetch fails", async () => {
  mockedApiGet.mockRejectedValue(new Error("network down"));
  renderPage();

  // One per section, on purpose: the two blocks fetch independently, so the
  // by-brand summary going down must not blank the feed as well.
  expect(await screen.findAllByRole("alert")).toHaveLength(2);
  expect(screen.getAllByText("Не удалось загрузить данные")).toHaveLength(2);
  expect(screen.queryByText("Отзывов пока нет")).not.toBeInTheDocument();

  const retryBtn = screen.getAllByRole("button", { name: "Повторить" })[0]!;
  mockApi();
  fireEvent.click(retryBtn);

  expect(await screen.findByText("Отличный сервис")).toBeInTheDocument();
});

it("names the brand and shows its logo instead of a raw id", async () => {
  // The column used to hold two UUIDs, so an operator had to open each one to
  // learn what the row was about.
  mockApi();
  renderPage();
  await screen.findByText("Отличный сервис");
  expect(screen.getAllByText("Roblox").length).toBeGreaterThan(0);
  const logos = Array.from(document.querySelectorAll("img")).map((i) => i.getAttribute("src"));
  expect(logos).toContain("https://cdn.example/roblox.png");
});

it("labels a guest as a guest and never links their email", async () => {
  // A dead link is worse than none, and a guest must not be mistakable for an
  // account at a glance.
  mockApi();
  renderPage();
  await screen.findByText("Отличный сервис");

  expect(screen.getByText("Гость")).toBeInTheDocument();
  const email = screen.getByText("guest@example.com");
  expect(email.closest("a")).toBeNull();

  // The signed-in author, by contrast, is a link to their card.
  expect(screen.getByText("Дарья").closest("a")).toHaveAttribute(
    "href",
    "/customers/user-bbbb2222",
  );
});

it("says a review has no text rather than printing a dash", async () => {
  mockApi();
  renderPage();
  expect(await screen.findByText("Без текста — только оценка")).toBeInTheDocument();
});

it("lists brands with their own totals and opens one on click", async () => {
  mockApi();
  renderPage();

  // The row carries a brand button too; the accordion header is the one
  // that owns aria-expanded.
  const header = (await screen.findAllByRole("button", { name: /Roblox/ })).find((b) =>
    b.hasAttribute("aria-expanded"),
  )!;
  expect(screen.getByText("2 отзывов")).toBeInTheDocument();
  expect(screen.getByText("★ 4.0")).toBeInTheDocument();

  fireEvent.click(header);
  await waitFor(() => {
    expect(header).toHaveAttribute("aria-expanded", "true");
  });
  // The brand's own list is a separate request, not a slice of the feed.
  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => String(p).includes("brand=roblox"))).toBe(true);
  });
});

it("pages the feed instead of capping it silently", async () => {
  mockApi();
  renderPage();
  await screen.findByText("Отличный сервис");

  // The count is shown even before anyone pages — it is the only confirmation
  // that a filter did what the operator meant.
  expect(screen.getAllByText(/из 45/).length).toBeGreaterThan(0);

  const next = screen.getAllByRole("button", { name: "Следующая страница" })[0]!;
  fireEvent.click(next);

  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => String(p).includes("offset=20"))).toBe(true);
  });
});

it("returns to the first page when the filter changes", async () => {
  // A page number only means something against the filter it was counted under;
  // staying on page 3 of a shorter result set reads as "nothing matched".
  mockApi();
  renderPage();
  await screen.findByText("Отличный сервис");

  fireEvent.click(screen.getAllByRole("button", { name: "Следующая страница" })[0]!);
  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => String(p).includes("offset=20"))).toBe(true);
  });

  mockedApiGet.mockClear();
  fireEvent.click(screen.getByLabelText("Только с жалобами"));

  await waitFor(() => {
    expect(mockedApiGet.mock.calls.length).toBeGreaterThan(0);
  });
  const feedCalls = mockedApiGet.mock.calls
    .map(([p]) => String(p))
    .filter((p) => p.includes("/admin/reviews?") && !p.includes("brand="));
  expect(feedCalls.every((p) => !p.includes("offset=20"))).toBe(true);
});

it("gives an opened brand its own pager, counted under the filter", async () => {
  mockApi();
  renderPage();
  const header = (await screen.findAllByRole("button", { name: /Roblox/ })).find((b) =>
    b.hasAttribute("aria-expanded"),
  )!;
  fireEvent.click(header);

  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => String(p).includes("brand=roblox"))).toBe(true);
  });
  // A page-sized request, not the whole brand in one silent slab.
  const brandCall = mockedApiGet.mock.calls
    .map(([p]) => String(p))
    .find((p) => p.includes("brand=roblox"))!;
  expect(brandCall).toContain("limit=20");
});
