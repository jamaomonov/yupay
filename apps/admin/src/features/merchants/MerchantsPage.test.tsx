// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { MerchantsPage } from "./MerchantsPage";

import type { MerchantListOut } from "./api";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

const LIST: MerchantListOut = {
  items: [
    {
      id: "m-active",
      title: "Pilot Reseller",
      status: "active",
      created_at: "2026-09-01T10:00:00Z",
      deposit_balance: "1250.00",
    },
    {
      id: "m-frozen",
      title: "Frozen Reseller",
      status: "frozen",
      created_at: "2026-08-20T10:00:00Z",
      deposit_balance: "0",
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/merchants"]}>
        <Routes>
          <Route path="/merchants" element={<MerchantsPage />} />
          <Route path="/merchants/:id" element={<div>detail-stub</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockResolvedValue(LIST);
});

it("renders every merchant with its USD balance and status", async () => {
  renderPage();
  expect(await screen.findByText("Pilot Reseller")).toBeInTheDocument();
  expect(screen.getByText("Frozen Reseller")).toBeInTheDocument();
  // Decimal strings rendered with a $ prefix — never floats.
  expect(screen.getByText("$1 250.00")).toBeInTheDocument();
  expect(screen.getByText("$0.00")).toBeInTheDocument();
  expect(screen.getByText("Активен")).toBeInTheDocument();
  expect(screen.getByText("Заморожен")).toBeInTheDocument();
});

it("creates a merchant from the dialog with an Idempotency-Key and lands on its page", async () => {
  mockedApiPost.mockResolvedValue({
    id: "m-new",
    title: "New Reseller",
    status: "active",
    created_at: "2026-09-06T10:00:00Z",
    deposit_balance: "0",
  });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Создать мерчанта" }));
  fireEvent.change(screen.getByLabelText("Название"), { target: { value: "  New Reseller  " } });
  fireEvent.click(screen.getByRole("button", { name: "Создать" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/merchants",
      { title: "New Reseller" },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
  // Success navigates straight to the new merchant's detail screen.
  expect(await screen.findByText("detail-stub")).toBeInTheDocument();
});

it("does not submit the create dialog with a blank title", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Создать мерчанта" }));
  const submit = screen.getByRole("button", { name: "Создать" });
  expect(submit).toBeDisabled();
  expect(mockedApiPost).not.toHaveBeenCalled();
});
