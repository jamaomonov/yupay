import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { PriceHistoryListOut } from "./types";

import { SkuPriceHistoryCard } from "./SkuPriceHistoryCard";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
}));

const mockedApiGet = vi.mocked(apiGet);

// Newest-first, as the API returns it — matches the /skus/{id} screenshot this
// was built from: 4 points bouncing between $1.0400 and $1.0510.
const HISTORY: PriceHistoryListOut = {
  items: [
    {
      id: "p4",
      sku_id: "sku-1",
      supplier_slug: "g2b",
      kind: "voucher",
      external_product_id: "107",
      external_variant_id: null,
      cost_usdt: "1.0400",
      previous_cost_usdt: "1.0510",
      source: "g2b",
      captured_at: "2026-08-13T00:59:00Z",
    },
    {
      id: "p3",
      sku_id: "sku-1",
      supplier_slug: "g2b",
      kind: "voucher",
      external_product_id: "107",
      external_variant_id: null,
      cost_usdt: "1.0510",
      previous_cost_usdt: "1.0400",
      source: "g2b",
      captured_at: "2026-08-12T10:59:00Z",
    },
    {
      id: "p2",
      sku_id: "sku-1",
      supplier_slug: "g2b",
      kind: "voucher",
      external_product_id: "107",
      external_variant_id: null,
      cost_usdt: "1.0400",
      previous_cost_usdt: "1.0510",
      source: "g2b",
      captured_at: "2026-08-12T05:59:00Z",
    },
    {
      id: "p1",
      sku_id: "sku-1",
      supplier_slug: "g2b",
      kind: "voucher",
      external_product_id: "107",
      external_variant_id: null,
      cost_usdt: "1.0510",
      previous_cost_usdt: null,
      source: "g2b",
      captured_at: "2026-08-11T06:59:00Z",
    },
  ],
};

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SkuPriceHistoryCard skuId="sku-1" skuCode="roblox-800" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("renders nothing while there is no history", async () => {
  mockedApiGet.mockResolvedValue({ items: [] } satisfies PriceHistoryListOut);
  const { container } = renderCard();

  await waitFor(() => {
    expect(container).toBeEmptyDOMElement();
  });
});

it("shows the compact summary and opens the full-history modal on click", async () => {
  mockedApiGet.mockImplementation((path) => {
    if (path.includes("limit=500")) return Promise.resolve(HISTORY);
    return Promise.resolve(HISTORY);
  });

  renderCard();

  expect(await screen.findByText("$1.0400")).toBeInTheDocument();
  expect(screen.getByText("$1.0510")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Вся история/i }));

  // The modal fetches its own copy at the server's max, not the card's 30.
  await waitFor(() => {
    expect(mockedApiGet).toHaveBeenCalledWith(
      expect.stringContaining("/sku-prices/sku-1/history?limit=500"),
    );
  });

  // Was → became is spelled out per row, not just the bare current price.
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("roblox-800");
  expect(dialog).toHaveTextContent("$1.0510");
  expect(dialog).toHaveTextContent("$1.0400");
  expect(dialog).toHaveTextContent("первая запись");
});

it("closes the modal on Escape", async () => {
  mockedApiGet.mockResolvedValue(HISTORY);
  renderCard();

  fireEvent.click(await screen.findByRole("button", { name: /Вся история/i }));
  await screen.findByRole("dialog");

  fireEvent.keyDown(window, { key: "Escape" });

  await waitFor(() => {
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
