// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { GiftsBrowser } from "./GiftsBrowser";

import type { GiftApp, GiftsList } from "@/lib/gifts";

/**
 * The Steam Gifts search + grid browser.
 *
 * Three properties matter most. An empty query costs nothing — it renders the
 * server-fetched `initial` page with no client fetch at all. Typing fires at
 * most one request per settled query, 400 ms after the last keystroke
 * (mirrors `PromoField.tsx`'s debounce). And "Показать ещё" always appends —
 * in plain browse mode (no search box query) just as much as mid-search — so
 * a visitor paging through the ~4k-game catalog never loses the page they
 * already have.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

// `GiftsBrowser` only imports `searchGifts` (plus the type-only `GiftApp`/
// `GiftsList`) from this module, so a plain replacement — no `importActual`
// — is enough.
vi.mock("@/lib/gifts", () => ({ searchGifts: vi.fn() }));

import { searchGifts } from "@/lib/gifts";

const searchGiftsMock = vi.mocked(searchGifts);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  searchGiftsMock.mockReset();
});

function makeApp(overrides: Partial<GiftApp> = {}): GiftApp {
  return {
    app_id: 1,
    name: "Steam Game",
    image: null,
    type: "game",
    price_usd: "9.99",
    price_uzs: "125000",
    discount_percent: null,
    packages_count: 1,
    dlc_count: 0,
    ...overrides,
  };
}

function renderBrowser(initial: GiftsList): void {
  render(<GiftsBrowser locale="ru" initial={initial} />);
}

it("renders the server-fetched initial page with no client fetch", () => {
  renderBrowser({ items: [makeApp({ app_id: 42, name: "Counter-Strike 2" })], total: 1 });

  expect(screen.getByText("Counter-Strike 2")).toBeInTheDocument();
  expect(searchGiftsMock).not.toHaveBeenCalled();
});

it("debounces keystrokes into a single search request", async () => {
  vi.useFakeTimers();
  searchGiftsMock.mockResolvedValue({ items: [], total: 0 });
  renderBrowser({ items: [], total: 0 });

  const input = screen.getByRole("searchbox");
  fireEvent.change(input, { target: { value: "d" } });
  fireEvent.change(input, { target: { value: "de" } });
  fireEvent.change(input, { target: { value: "dea" } });
  fireEvent.change(input, { target: { value: "dead" } });

  // Not yet — the debounce window hasn't elapsed.
  expect(searchGiftsMock).not.toHaveBeenCalled();

  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  // The fetch kicks off from the effect the timer's state update triggers,
  // one tick later — `waitFor` covers that gap, same as the other tests
  // below.
  await waitFor(() => {
    expect(searchGiftsMock).toHaveBeenCalledTimes(1);
  });
  expect(searchGiftsMock).toHaveBeenCalledWith("ru", "dead", 0);
});

it("renders the search results once the debounced request resolves", async () => {
  vi.useFakeTimers();
  searchGiftsMock.mockResolvedValue({
    items: [makeApp({ app_id: 7, name: "Hollow Knight" })],
    total: 1,
  });
  renderBrowser({ items: [], total: 0 });

  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "hollow" } });
  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  await waitFor(() => {
    expect(screen.getByText("Hollow Knight")).toBeInTheDocument();
  });
});

it("shows the empty state when a search finds nothing", async () => {
  vi.useFakeTimers();
  searchGiftsMock.mockResolvedValue({ items: [], total: 0 });
  renderBrowser({ items: [makeApp({ name: "Should disappear" })], total: 1 });

  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz" } });
  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  await waitFor(() => {
    expect(screen.getByText("search.empty")).toBeInTheDocument();
  });
  expect(screen.queryByText("Should disappear")).not.toBeInTheDocument();
});

it("shows an error with a retry action when the search fails", async () => {
  vi.useFakeTimers();
  searchGiftsMock.mockRejectedValue(new Error("boom"));
  renderBrowser({ items: [], total: 0 });

  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "boom" } });
  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  await waitFor(() => {
    expect(screen.getByText("search.error")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "search.retry" })).toBeInTheDocument();
});

it('appends (not replaces) the next page of search results on "show more"', async () => {
  vi.useFakeTimers();
  searchGiftsMock.mockResolvedValue({
    items: [makeApp({ app_id: 1, name: "Page one" })],
    total: 2,
  });
  renderBrowser({ items: [], total: 0 });

  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "page" } });
  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  await waitFor(() => {
    expect(screen.getByText("Page one")).toBeInTheDocument();
  });

  searchGiftsMock.mockResolvedValue({
    items: [makeApp({ app_id: 2, name: "Page two" })],
    total: 2,
  });
  fireEvent.click(screen.getByRole("button", { name: "search.showMore" }));

  await waitFor(() => {
    expect(searchGiftsMock).toHaveBeenLastCalledWith("ru", "page", 1);
  });
  await waitFor(() => {
    expect(screen.getByText("Page two")).toBeInTheDocument();
  });
  // The append, not replace: page one must still be on screen.
  expect(screen.getByText("Page one")).toBeInTheDocument();
});

it('paginates the default browse list on "show more" — no search query typed', async () => {
  // This is the bug this test guards against: with an empty query the grid
  // was `initial` and pagination never fetched anything, so a visitor could
  // only ever see the first page of the ~4k-game catalog.
  renderBrowser({ items: [makeApp({ app_id: 1, name: "Browse page one" })], total: 2 });

  expect(searchGiftsMock).not.toHaveBeenCalled();

  searchGiftsMock.mockResolvedValue({
    items: [makeApp({ app_id: 2, name: "Browse page two" })],
    total: 2,
  });
  fireEvent.click(screen.getByRole("button", { name: "search.showMore" }));

  // Empty query, offset = the one item already showing — same endpoint plain
  // browsing uses (`/gifts/catalog?offset=1`, no `search` param).
  await waitFor(() => {
    expect(searchGiftsMock).toHaveBeenCalledWith("ru", "", 1);
  });
  await waitFor(() => {
    expect(screen.getByText("Browse page two")).toBeInTheDocument();
  });
  expect(screen.getByText("Browse page one")).toBeInTheDocument();
});
