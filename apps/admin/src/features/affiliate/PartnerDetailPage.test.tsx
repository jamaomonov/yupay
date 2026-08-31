import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { PartnerDetailPage } from "./PartnerDetailPage";

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

/**
 * The two bugs that forced this page into existence, pinned as tests: a
 * suspended partner could not be reactivated (the endpoint did not exist),
 * and the issue-a-code button never learned a code had been issued (the list
 * page could not see codes at all).
 */

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);
const mockedApiPatch = vi.mocked(apiPatch);
const mockedApiDelete = vi.mocked(apiDelete);

function detail(partnerStatus: string, codes: unknown[]) {
  return {
    partner: {
      id: "p-1",
      email: "p@example.test",
      display_name: "Jamshid",
      contact: "@jama",
      channel: "https://youtube.com/@jama",
      status: partnerStatus,
      admin_note: null,
      created_at: "2026-08-01T00:00:00Z",
      approved_at: null,
    },
    codes,
    stats_month: {
      period: "month",
      since: "2026-08-01T00:00:00Z",
      earned: "12000",
      orders: 3,
      activations: 5,
    },
    stats_year: {
      period: "year",
      since: "2025-08-31T00:00:00Z",
      earned: "12000",
      orders: 3,
      activations: 5,
    },
    balance: { available: "12000", held: "0", reserved: "0" },
  };
}

const ACTIVE_CODE = {
  id: "c-1",
  code: "JAMA10",
  discount_percent: "5",
  commission_percent: "2",
  active: true,
  created_at: "2026-08-02T00:00:00Z",
};

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiPatch.mockReset();
  mockedApiDelete.mockReset();
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/affiliate/partners/p-1"]}>
        <Routes>
          <Route path="/affiliate/partners/:id" element={<PartnerDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("a suspended partner can be reactivated", async () => {
  mockedApiGet.mockResolvedValue(detail("suspended", [ACTIVE_CODE]));
  mockedApiPost.mockResolvedValue({});
  renderPage();

  const activate = await screen.findByRole("button", { name: "Активировать" });
  expect(screen.queryByRole("button", { name: "Отключить" })).toBeNull();
  fireEvent.click(activate);

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/affiliate/partners/p-1/unsuspend",
      {},
    );
  });
});

it("an issued code demotes the issue button instead of leaving it primary", async () => {
  mockedApiGet.mockResolvedValue(detail("active", [ACTIVE_CODE]));
  renderPage();

  await screen.findByText("JAMA10");
  expect(screen.queryByRole("button", { name: "Выдать код" })).toBeNull();
  expect(screen.getByRole("button", { name: "Выдать ещё код" })).toBeInTheDocument();
});

it("with no codes the primary issue button is offered", async () => {
  mockedApiGet.mockResolvedValue(detail("active", []));
  renderPage();

  expect(await screen.findByRole("button", { name: "Выдать код" })).toBeInTheDocument();
});

it("editing the profile PATCHes only this partner", async () => {
  mockedApiGet.mockResolvedValue(detail("active", []));
  mockedApiPatch.mockResolvedValue({});
  renderPage();

  const name = await screen.findByLabelText("Имя");
  fireEvent.change(name, { target: { value: "Jamshid O." } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledWith(
      "/api/v1/admin/affiliate/partners/p-1",
      expect.objectContaining({ display_name: "Jamshid O." }),
    );
  });
});

it("retuning a code PATCHes its percents", async () => {
  mockedApiGet.mockResolvedValue(detail("active", [ACTIVE_CODE]));
  mockedApiPatch.mockResolvedValue({ ...ACTIVE_CODE, discount_percent: "7" });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
  fireEvent.change(screen.getByLabelText("Скидка JAMA10"), { target: { value: "7" } });
  // Two save buttons exist (profile + code row) — the code row's is the
  // enabled one, the profile's is disabled while the form is pristine.
  const save = screen
    .getAllByRole("button", { name: "Сохранить" })
    .find((b) => !(b as HTMLButtonElement).disabled);
  expect(save).toBeDefined();
  fireEvent.click(save as HTMLElement);

  await waitFor(() => {
    expect(mockedApiPatch).toHaveBeenCalledWith(
      "/api/v1/admin/affiliate/codes/c-1",
      expect.objectContaining({ discount_percent: "7", commission_percent: "2" }),
    );
  });
});

it("deleting a code asks first, then DELETEs", async () => {
  mockedApiGet.mockResolvedValue(detail("active", [ACTIVE_CODE]));
  mockedApiDelete.mockResolvedValue(undefined);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));

  await waitFor(() => {
    expect(mockedApiDelete).toHaveBeenCalledWith("/api/v1/admin/affiliate/codes/c-1");
  });
  confirmSpy.mockRestore();
});
