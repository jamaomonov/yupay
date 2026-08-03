import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProvidersPage } from "./ProvidersPage";

import type { AdminProviderDetailOut, AdminProviderListOut, AdminProviderSummary } from "./types";

import { api, apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiGet: vi.fn(),
}));

const mockedApi = vi.mocked(api);
const mockedApiGet = vi.mocked(apiGet);

const CLICK_SUMMARY: AdminProviderSummary = {
  provider: "click",
  display_name: "Click",
  slugs: ["click", "uzcard", "humo"],
  config_available: true,
  state: "active",
  changed_by: "11111111-2222-3333-4444-555555555555",
  changed_at: "2026-07-01T08:00:00Z",
};

const PROVIDERS: AdminProviderListOut = { providers: [CLICK_SUMMARY] };

const DETAIL: AdminProviderDetailOut = {
  summary: CLICK_SUMMARY,
  volume: [{ currency: "UZS", amount: "1000000.000000", count: 12 }],
  success_rate: { succeeded: 10, failed: 1, pending: 1, success_pct: 83.3 },
  recent: [],
  incidents: { stuck_pending: 0, failed_webhooks: 1 },
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProvidersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApi.mockReset();
  mockedApiGet.mockReset();
});

it("renders providers from the list endpoint with a state badge", async () => {
  mockedApiGet.mockResolvedValue(PROVIDERS);
  renderPage();

  expect(await screen.findByText("Click")).toBeInTheDocument();
  expect(screen.getByText("click")).toBeInTheDocument();
  expect(screen.getByText("Активен")).toBeInTheDocument();
  expect(screen.getByText("Настроен")).toBeInTheDocument();
});

it("disables a provider through the confirm dialog and calls the PUT state endpoint", async () => {
  mockedApiGet.mockImplementation((path) => {
    if (path.includes("/providers/click?")) {
      return Promise.resolve(DETAIL);
    }
    return Promise.resolve(PROVIDERS);
  });
  mockedApi.mockResolvedValue({ ...CLICK_SUMMARY, state: "disabled" });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

  renderPage();

  fireEvent.click(await screen.findByText("Click"));

  const disableBtn = await screen.findByRole("button", { name: "Отключить" });
  fireEvent.click(disableBtn);

  expect(confirmSpy).toHaveBeenCalled();

  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalledWith(
      "/api/v1/admin/payments/providers/click/state",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ state: "disabled" }),
        headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
      }),
    );
  });

  confirmSpy.mockRestore();
});

it("does not call the PUT endpoint when the disable confirmation is dismissed", async () => {
  mockedApiGet.mockImplementation((path) => {
    if (path.includes("/providers/click?")) {
      return Promise.resolve(DETAIL);
    }
    return Promise.resolve(PROVIDERS);
  });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

  renderPage();

  fireEvent.click(await screen.findByText("Click"));
  const disableBtn = await screen.findByRole("button", { name: "Отключить" });
  fireEvent.click(disableBtn);

  expect(confirmSpy).toHaveBeenCalled();
  expect(mockedApi).not.toHaveBeenCalled();

  confirmSpy.mockRestore();
});

afterEach(() => {
  vi.restoreAllMocks();
});
