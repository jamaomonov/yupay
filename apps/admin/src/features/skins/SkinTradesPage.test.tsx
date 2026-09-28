// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinTradesPage } from "./SkinTradesPage";

import type { AdminSkinTradesOut } from "./api";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const PAGE: AdminSkinTradesOut = {
  total: 1,
  items: [
    {
      id: "t1",
      order_id: "01a0e987-eede-7d40-892f-fe7f3b3bd0e9",
      order_item_id: "i1",
      created_at: "2026-09-29T10:00:00Z",
      market_hash_name: "AK-47 | Redline (Field-Tested)",
      phase: "",
      paid_units: 27867,
      bought_units: 27000,
      waxpeer_status: 6,
      state: "failed",
      reason_code: "other",
      reason: "rollback",
      penalties: { total_penalty: 1500 },
      seller_name: "darpan6awx",
      trade_id: "9393511289",
      send_until: null,
      release_date: "2026-10-05T16:00:00Z",
      accepted_at: "2026-09-28T16:00:00Z",
      last_checked_at: null,
      task_status: "succeeded",
      task_sub_state: null,
      attention: true,
    },
  ],
};

function renderPage(entry = "/skins/trades") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/skins/trades" element={<SkinTradesPage />} />
          <Route path="/orders/:id" element={<div>order-stub</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

it("lists trades with the dollars paid, the seller and a flag for attention", async () => {
  mockedApiGet.mockResolvedValue(PAGE);
  renderPage();
  expect(await screen.findByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
  expect(screen.getByText("$27.00")).toBeInTheDocument();
  expect(screen.getByText("darpan6awx")).toBeInTheDocument();
  expect(screen.getByText(/Штраф: 1500/)).toBeInTheDocument();
  expect(mockedApiGet.mock.calls[0]![0]).toContain("view=all");
});

it("asks for the trades needing a human on that tab", async () => {
  mockedApiGet.mockResolvedValue(PAGE);
  renderPage();
  fireEvent.click(await screen.findByRole("tab", { name: /Требуют внимания/ }));
  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => p.includes("view=attention"))).toBe(true);
  });
});

it("opens the order on a row click", async () => {
  mockedApiGet.mockResolvedValue(PAGE);
  renderPage();
  fireEvent.click(await screen.findByText("AK-47 | Redline (Field-Tested)"));
  expect(await screen.findByText("order-stub")).toBeInTheDocument();
});

it("says so when there are none", async () => {
  mockedApiGet.mockResolvedValue({ total: 0, items: [] });
  renderPage();
  expect(await screen.findByText("Обменов нет")).toBeInTheDocument();
});
