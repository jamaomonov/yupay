// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePolicyCard } from "./PurchasePolicyCard";

import type { UserAdminOut } from "@/features/users/types";

import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  formatApiError: (err: Error) => err.message,
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

const mockedApi = vi.mocked(api);

const USER: UserAdminOut = {
  id: "01a004c3-0000-0000-0000-000000000001",
  email: "buyer@example.com",
  locale: "ru",
  display_currency: "UZS",
  display_name: "Buyer",
  photo_url: null,
  roles: [],
  created_at: "2026-10-11T10:00:00Z",
  updated_at: "2026-10-11T10:00:00Z",
  deleted_at: null,
  banned_at: null,
  ban_reason: null,
  banned_by: null,
  purchase_limit_usd: null,
  trusted_at: null,
  trusted_by: null,
  telegram_link: null,
  steam_link: null,
  wallet_balances: [],
};

function renderCard(user: UserAdminOut) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PurchasePolicyCard user={user} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

it("saves a limit and keeps the trusted flag as it was", async () => {
  mockedApi.mockResolvedValue({ ...USER, purchase_limit_usd: "30.00" });
  renderCard(USER);
  fireEvent.change(screen.getByLabelText(/Лимит/), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalledWith(
      `/api/v1/admin/users/${USER.id}/purchase-policy`,
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ trusted: false, purchase_limit_usd: "30" }),
      }),
    );
  });
});

it("refuses a malformed limit", () => {
  renderCard(USER);
  fireEvent.change(screen.getByLabelText(/Лимит/), { target: { value: "10$" } });
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
});

it("marks a trusted account and can lift the mark", async () => {
  mockedApi.mockResolvedValue(USER);
  renderCard({ ...USER, trusted_at: "2026-10-11T10:00:00Z", purchase_limit_usd: "50.00" });
  expect(screen.getByText("Доверенный")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Снять отметку" }));
  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({ trusted: false, purchase_limit_usd: "50.00" }),
      }),
    );
  });
});
