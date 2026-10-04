// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { P2PCardsPage } from "./P2PCardsPage";

import type { P2PCard, P2PSettings } from "./api";

import { apiGet, apiPatch, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const get = vi.mocked(apiGet);
const patch = vi.mocked(apiPatch);
const post = vi.mocked(apiPost);

const SETTINGS: P2PSettings = {
  mode: "off",
  allowlist_merchant_ids: [],
  humo_bot_user_id: null,
  updated_at: "2026-10-04T10:00:00Z",
};
const CARD: P2PCard = {
  id: "c1",
  label: "Основная",
  pan_last4: "3311",
  holder_name: "A B",
  network: "humo",
  active: true,
  min_amount_uzs: 10000,
  max_amount_uzs: 10000000,
  daily_limit_uzs: null,
  matched_today_uzs: 150000,
  last_incoming_at: null,
  chain_ok_last: false,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <P2PCardsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  post.mockReset();
  get.mockImplementation((path: string) =>
    Promise.resolve(path.endsWith("/settings") ? SETTINGS : [CARD]),
  );
});

it("shows the card by its last four digits only", async () => {
  renderPage();
  expect(await screen.findByText("*3311")).toBeInTheDocument();
  expect(screen.getByText("разрыв баланса")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/\d{16}/);
});

it("saves settings with an Idempotency-Key header", async () => {
  patch.mockResolvedValue({ ...SETTINGS, mode: "all" });
  renderPage();
  await screen.findByText("*3311");
  fireEvent.change(screen.getByRole("combobox", { name: /Кому доступно/ }), {
    target: { value: "all" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalledWith(
      "/api/v1/admin/p2p/settings",
      expect.objectContaining({ mode: "all" }),
      expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
    );
  });
});

it("edits a card without sending the number unless a new one is typed", async () => {
  patch.mockResolvedValue(CARD);
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
  expect(screen.getByPlaceholderText("•••• 3311")).toHaveValue("");
  fireEvent.change(screen.getByDisplayValue("Основная"), { target: { value: "Запасная" } });
  fireEvent.click(within(screen.getByRole("form")).getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(patch).toHaveBeenCalled();
  });
  const body = patch.mock.calls.find(([p]) => p.includes("/cards/"))?.[1] as Record<
    string,
    unknown
  >;
  expect(body).toMatchObject({ label: "Запасная" });
  expect(body).not.toHaveProperty("pan");
});
