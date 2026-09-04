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
