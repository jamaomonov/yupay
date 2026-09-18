import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SupplierDetailPage } from "./SupplierDetailPage";

import { apiGet } from "@/lib/api";

/**
 * Waxpeer was integrated for Steam top-ups and had a balance probe the whole
 * time, but no way to reach it: the integrations index listed only G2B, and
 * the health route branched per supplier instead of asking the fulfiller.
 *
 * It also has no catalogue — a Steam top-up is priced by the amount typed, so
 * there is no product list to sync or map a SKU onto (zero rows in both tables
 * on production). Offering those actions would be offering buttons that can
 * only fail.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

function mockHealth(supplier: string, over: Record<string, unknown> = {}) {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/health")) {
      return Promise.resolve({
        supplier,
        available: true,
        reason: null,
        balance: "54.05",
        currency: "USD",
        username: null,
        last_checked_at: "2026-08-17T00:00:00Z",
        ...over,
      });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

function renderAt(slug: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/integrations/${slug}`]}>
        <Routes>
          <Route path="/integrations/:slug" element={<SupplierDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

it("shows Waxpeer's balance, which had no way of being seen before", async () => {
  mockHealth("waxpeer");
  renderAt("waxpeer");

  expect(await screen.findByRole("heading", { name: "Waxpeer" })).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText(/54\.05/)).toBeInTheDocument();
  });
});

it("offers no catalogue tooling for a supplier that has no catalogue", async () => {
  mockHealth("waxpeer");
  renderAt("waxpeer");
  await screen.findByRole("heading", { name: "Waxpeer" });

  expect(screen.queryByText("Каталог поставщика")).not.toBeInTheDocument();
  expect(screen.queryByText("Маппинг SKU")).not.toBeInTheDocument();
  // And says why, so the absence reads as deliberate rather than broken.
  expect(screen.getByText(/нет списка товаров/)).toBeInTheDocument();
});

it("keeps the catalogue tooling for G2B", async () => {
  mockHealth("g2b", { balance: "22.52", username: "jama_omonov" });
  renderAt("g2b");

  expect(await screen.findByText("Каталог поставщика")).toBeInTheDocument();
  expect(screen.getByText("Маппинг SKU")).toBeInTheDocument();
});

it("still lists the interaction log for both", async () => {
  mockHealth("waxpeer");
  renderAt("waxpeer");

  expect(await screen.findByText("Последние взаимодействия")).toBeInTheDocument();
});

it("offers full catalogue tooling to G-Engine now that it has a sync endpoint", async () => {
  // G-Engine used to have no sync-catalog route, so this page hid
  // "Синхронизировать каталог" / "Просмотр каталога" / "Обновить цены" behind
  // a `catalogue: false` flag and told the operator to type ids by hand
  // instead. This branch added the endpoint; the tooling — and the mapping
  // card, which was never gated on it — must all show now, and the stale
  // by-hand note must be gone.
  mockHealth("gengine");
  renderAt("gengine");
  await screen.findByRole("heading", { name: "G-Engine" });

  expect(screen.getByText("Маппинг SKU")).toBeInTheDocument();
  expect(screen.getByText("Каталог поставщика")).toBeInTheDocument();
  expect(screen.getByText("Просмотр каталога")).toBeInTheDocument();
  expect(screen.getByText("Цены маппингов")).toBeInTheDocument();
  expect(screen.queryByText(/service_id/)).not.toBeInTheDocument();
});

it("offers full catalogue tooling to NOVA now that it has a sync endpoint too", async () => {
  mockHealth("nova");
  renderAt("nova");
  await screen.findByRole("heading", { name: "NOVA" });

  expect(screen.getByText("Маппинг SKU")).toBeInTheDocument();
  expect(screen.getByText("Каталог поставщика")).toBeInTheDocument();
  expect(screen.getByText("Просмотр каталога")).toBeInTheDocument();
  // The stale by-hand note ("category_id... offer_id...") must be gone.
  expect(screen.queryByText(/category_id/)).not.toBeInTheDocument();
});
