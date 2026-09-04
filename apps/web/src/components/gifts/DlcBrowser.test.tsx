// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DlcBrowser, DlcNote } from "./DlcBrowser";

import type { GiftApp } from "@/lib/gifts";

/**
 * The per-game DLC list: collapsed behind a "DLC: N — показать" toggle,
 * expanding on tap into a search box + one page (≤24) of results — never
 * more than one page mounted at a time, unlike `GiftsBrowser`'s
 * accumulate-on-"Показать ещё".
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

vi.mock("@/lib/gifts", () => ({ fetchGiftDlc: vi.fn() }));

import { fetchGiftDlc } from "@/lib/gifts";

const fetchGiftDlcMock = vi.mocked(fetchGiftDlc);

afterEach(() => {
  vi.useRealTimers();
  fetchGiftDlcMock.mockReset();
});

function makeApp(overrides: Partial<GiftApp> = {}): GiftApp {
  return {
    app_id: 100,
    name: "Some DLC",
    image: null,
    type: "dlc",
    price_usd: "4.99",
    price_uzs: "62000",
    discount_percent: null,
    packages_count: 1,
    dlc_count: 0,
    ...overrides,
  };
}

it("shows the base-game-required note on a DLC's own page", () => {
  render(<DlcNote type="dlc" />);
  expect(screen.getByText("dlcNote")).toBeInTheDocument();
});

it("renders nothing on a base game's page", () => {
  const { container } = render(<DlcNote type="game" />);
  expect(container).toBeEmptyDOMElement();
});

it("renders nothing when the app has no DLC", () => {
  const { container } = render(<DlcBrowser appId={1} total={0} locale="ru" />);
  expect(container).toBeEmptyDOMElement();
});

it("is collapsed by default — shows the toggle and fetches nothing", () => {
  render(<DlcBrowser appId={1} total={423} locale="ru" />);

  expect(screen.getByText('dlc.toggle:{"count":423}')).toBeInTheDocument();
  expect(fetchGiftDlcMock).not.toHaveBeenCalled();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
});

it("fetches page 1 on expand", async () => {
  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 1, name: "Soundtrack" })],
    total: 2,
  });
  render(<DlcBrowser appId={588650} total={2} locale="ru" />);

  fireEvent.click(screen.getByText('dlc.toggle:{"count":2}'));

  expect(fetchGiftDlcMock).toHaveBeenCalledWith("ru", 588650, "", 0);
  await waitFor(() => {
    expect(screen.getByText("Soundtrack")).toBeInTheDocument();
  });
  expect(screen.getByRole("searchbox")).toBeInTheDocument();
});

it("narrows results with a debounced search", async () => {
  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 1, name: "Every DLC" })],
    total: 1,
  });
  render(<DlcBrowser appId={588650} total={1} locale="ru" />);
  fireEvent.click(screen.getByText('dlc.toggle:{"count":1}'));
  await waitFor(() => {
    expect(screen.getByText("Every DLC")).toBeInTheDocument();
  });

  vi.useFakeTimers();
  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 2, name: "Soundtrack DLC" })],
    total: 1,
  });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "sound" } });

  // Not yet — the debounce window hasn't elapsed.
  expect(fetchGiftDlcMock).toHaveBeenCalledTimes(1);

  await vi.advanceTimersByTimeAsync(400);
  vi.useRealTimers();

  await waitFor(() => {
    expect(fetchGiftDlcMock).toHaveBeenLastCalledWith("ru", 588650, "sound", 0);
  });
  await waitFor(() => {
    expect(screen.getByText("Soundtrack DLC")).toBeInTheDocument();
  });
  // Narrowed, not appended: the earlier result is gone.
  expect(screen.queryByText("Every DLC")).not.toBeInTheDocument();
});

it("shows an error with retry when a page fails to load", async () => {
  fetchGiftDlcMock.mockRejectedValue(new Error("boom"));
  render(<DlcBrowser appId={588650} total={5} locale="ru" />);

  fireEvent.click(screen.getByText('dlc.toggle:{"count":5}'));

  await waitFor(() => {
    expect(screen.getByText("search.error")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "search.retry" })).toBeInTheDocument();
});

it("pages forward without accumulating the previous page", async () => {
  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 1, name: "Page one item" })],
    total: 26,
  });
  render(<DlcBrowser appId={588650} total={26} locale="ru" />);
  fireEvent.click(screen.getByText('dlc.toggle:{"count":26}'));
  await waitFor(() => {
    expect(screen.getByText("Page one item")).toBeInTheDocument();
  });

  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 2, name: "Page two item" })],
    total: 26,
  });
  fireEvent.click(screen.getByLabelText("dlc.nextPage"));

  await waitFor(() => {
    expect(fetchGiftDlcMock).toHaveBeenLastCalledWith("ru", 588650, "", 24);
  });
  await waitFor(() => {
    expect(screen.getByText("Page two item")).toBeInTheDocument();
  });
  // Replaced, not appended: never more than one page (24) on screen at once.
  expect(screen.queryByText("Page one item")).not.toBeInTheDocument();
});

it('shows "N–M из TOTAL" next to the pager', async () => {
  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 1, name: "Page one item" })],
    total: 26,
  });
  render(<DlcBrowser appId={588650} total={26} locale="ru" />);
  fireEvent.click(screen.getByText('dlc.toggle:{"count":26}'));

  await waitFor(() => {
    expect(screen.getByText('dlc.pageRange:{"from":1,"to":24,"total":26}')).toBeInTheDocument();
  });

  fetchGiftDlcMock.mockResolvedValue({
    items: [makeApp({ app_id: 2, name: "Page two item" })],
    total: 26,
  });
  fireEvent.click(screen.getByLabelText("dlc.nextPage"));

  await waitFor(() => {
    expect(screen.getByText('dlc.pageRange:{"from":25,"to":26,"total":26}')).toBeInTheDocument();
  });
});

/**
 * The pager used to unmount entirely while `phase === "loading"` (the grid
 * became a skeleton and the buttons vanished with it), which meant a tap on
 * "next" could land on nothing — the control disappeared out from under the
 * buyer's thumb. It now stays mounted, just disabled, through the fetch
 * (2026-09-04 review).
 */
it("keeps the pager mounted (disabled, not gone) while the next page is loading", async () => {
  let resolveFetch: (value: {
    items: ReturnType<typeof makeApp>[];
    total: number;
  }) => void = () => {
    throw new Error("resolveFetch called before assignment");
  };
  fetchGiftDlcMock.mockResolvedValueOnce({
    items: [makeApp({ app_id: 1, name: "Page one item" })],
    total: 26,
  });
  render(<DlcBrowser appId={588650} total={26} locale="ru" />);
  fireEvent.click(screen.getByText('dlc.toggle:{"count":26}'));
  await waitFor(() => {
    expect(screen.getByText("Page one item")).toBeInTheDocument();
  });

  fetchGiftDlcMock.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
  );
  fireEvent.click(screen.getByLabelText("dlc.nextPage"));

  // Still in the document, but both directions disabled while the fetch is
  // in flight — not unmounted.
  expect(screen.getByLabelText("dlc.nextPage")).toBeDisabled();
  expect(screen.getByLabelText("dlc.prevPage")).toBeDisabled();
  expect(screen.getByText('dlc.pageRange:{"from":1,"to":24,"total":26}')).toBeInTheDocument();

  resolveFetch({ items: [makeApp({ app_id: 2, name: "Page two item" })], total: 26 });
  // Offset moved from 0 to 24 — "previous" is enabled again once the fetch
  // resolves ("next" stays disabled: 26 items don't reach a third page).
  await waitFor(() => {
    expect(screen.getByLabelText("dlc.prevPage")).not.toBeDisabled();
  });
  expect(screen.getByLabelText("dlc.nextPage")).toBeDisabled();
});

it("adds aria-expanded to the collapsed toggle", () => {
  render(<DlcBrowser appId={1} total={5} locale="ru" />);
  expect(screen.getByText('dlc.toggle:{"count":5}')).toHaveAttribute("aria-expanded", "false");
});
