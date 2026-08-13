// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SkuEditPage } from "./SkuEditPage";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const RATES = {
  base: "USD",
  rates: [
    {
      base: "USD",
      quote: "UZS",
      rate: "12700",
      fetched_at: "2026-01-01T00:00:00Z",
      source: "test",
    },
    { base: "USD", quote: "RUB", rate: "95", fetched_at: "2026-01-01T00:00:00Z", source: "test" },
  ],
};

function mockCatalog(): void {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/fx/rates")) return Promise.resolve(RATES);
    // products / brands / skus — a bare list page doesn't need a selected
    // product to exercise the price/margin math, which is independent of it.
    return Promise.resolve([]);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/skus/new"]}>
        <SkuEditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockCatalog();
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("hides the margin field until a valid cost is entered", async () => {
  renderPage();
  expect(screen.queryByPlaceholderText("20")).not.toBeInTheDocument();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "0" } });
  expect(screen.queryByPlaceholderText("20")).not.toBeInTheDocument();

  fireEvent.change(cost, { target: { value: "1" } });
  expect(await screen.findByPlaceholderText("20")).toBeInTheDocument();
});

it("computes price_usd from cost and a typed margin percent", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "1" } });

  const margin = await screen.findByPlaceholderText("20");
  fireEvent.change(margin, { target: { value: "25" } });

  const price = screen.getByPlaceholderText("0.85") as HTMLInputElement;
  await waitFor(() => {
    expect(price.value).toBe("1.25");
  });
});

it("computes margin percent from cost and a typed price_usd", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "2" } });

  const price = screen.getByPlaceholderText("0.85");
  fireEvent.change(price, { target: { value: "3" } });

  const margin = (await screen.findByPlaceholderText("20")) as HTMLInputElement;
  await waitFor(() => {
    expect(margin.value).toBe("50");
  });
});

it("re-derives margin from the new cost, keeping price_usd put", async () => {
  renderPage();

  const cost = await screen.findByPlaceholderText("0.60");
  fireEvent.change(cost, { target: { value: "1" } });
  const price = screen.getByPlaceholderText("0.85") as HTMLInputElement;
  fireEvent.change(price, { target: { value: "1.50" } });
  const margin = (await screen.findByPlaceholderText("20")) as HTMLInputElement;
  await waitFor(() => {
    expect(margin.value).toBe("50");
  });

  // Cost moves (e.g. the supplier's price changed) — price_usd is left as
  // the operator set it, margin catches up to the new ratio instead.
  fireEvent.change(cost, { target: { value: "1.25" } });
  await waitFor(() => {
    expect(margin.value).toBe("20");
  });
  expect(price.value).toBe("1.50");
});

it("previews the USD price converted per FX rate, and prefers a currency override over the conversion", async () => {
  renderPage();

  const price = await screen.findByPlaceholderText("0.85");
  fireEvent.change(price, { target: { value: "10" } });

  // Override RUB at 999 — the FX conversion would say 950 (10 × 95).
  fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
  fireEvent.change(screen.getByLabelText("Валюта переопределения цены"), {
    target: { value: "RUB" },
  });
  fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "999" } });

  fireEvent.click(screen.getByRole("button", { name: /Превью цены в других валютах/i }));

  const panel = await screen.findByRole("dialog", { name: "Цены в других валютах" });
  expect(within(panel).getByText("999")).toBeInTheDocument();
  // Exact, case-sensitive: the footer note also contains the word
  // "Override" (capitalised, mid-sentence) — only the badge is "override".
  expect(within(panel).getByText("override")).toBeInTheDocument();
  expect(within(panel).queryByText("950")).not.toBeInTheDocument();
});
