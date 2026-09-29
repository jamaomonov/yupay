// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { CustomerSkins } from "./CustomerSkins";

import type { AdminSkinTradeOut } from "./api";
import type { CustomerSkinsOut } from "./customer-api";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);

const TRADE: AdminSkinTradeOut = {
  id: "t1",
  project_id: "p-1",
  waxpeer_id: null,
  order_id: "01a0e987-eede-7d40-892f-fe7f3b3bd0e9",
  order_item_id: "i1",
  created_at: "2026-09-29T10:00:00Z",
  market_hash_name: "AK-47 | Slate (Battle-Scarred)",
  phase: "",
  image_url: null,
  sold_usd: "3.40",
  paid_units: 3100,
  bought_units: 3100,
  waxpeer_status: 5,
  state: "released",
  reason_code: null,
  reason: null,
  penalties: null,
  seller_name: null,
  trade_id: null,
  offer_url: null,
  send_until: null,
  release_date: null,
  accepted_at: null,
  last_checked_at: null,
  task_id: null,
  task_status: "succeeded",
  task_sub_state: null,
  refunded_to: null,
  can_refund: true,
  can_retry: false,
  resolved_at: null,
  resolved_note: null,
  attention: false,
};

function renderIt(body: CustomerSkinsOut) {
  mockedApiGet.mockResolvedValue(body);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CustomerSkins userId="u1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

it("shows the Steam accounts and the skins bought", async () => {
  renderIt({
    saved: {
      steam_id: "76561199000000000",
      profile_url: "https://steamcommunity.com/profiles/76561199000000000",
      updated_at: "2026-09-29T10:00:00Z",
    },
    accounts: [
      {
        steam_id: "76561199000000000",
        profile_url: "https://steamcommunity.com/profiles/76561199000000000",
        orders: 3,
      },
    ],
    trades: [TRADE],
  });
  expect(await screen.findByText("AK-47 | Slate (Battle-Scarred)")).toBeInTheDocument();
  const links = screen.getAllByRole("link", { name: /76561199000000000/ });
  expect(links[0]).toHaveAttribute("href", "https://steamcommunity.com/profiles/76561199000000000");
  expect(screen.getByText(/3 заказ/)).toBeInTheDocument();
  expect(mockedApiGet).toHaveBeenCalledWith("/api/v1/admin/skins/customers/u1");
});

it("renders nothing for a customer who never touched skins", async () => {
  const { container } = renderIt({ saved: null, accounts: [], trades: [] });
  await vi.waitFor(() => {
    expect(mockedApiGet).toHaveBeenCalled();
  });
  expect(container).toBeEmptyDOMElement();
});
