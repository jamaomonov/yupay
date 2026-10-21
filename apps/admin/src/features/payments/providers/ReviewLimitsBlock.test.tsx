import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { type ReviewLimit, ReviewLimitsBlock } from "./ReviewLimitsBlock";

import { api, apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiGet: vi.fn(),
  formatApiError: () => "error",
}));

const mockedApi = vi.mocked(api);
const mockedApiGet = vi.mocked(apiGet);

const row = (provider: string, over: Partial<ReviewLimit> = {}): ReviewLimit => ({
  provider,
  enabled: false,
  max_amount: null,
  currency: "UZS",
  window_hours: 24,
  changed_by: null,
  changed_at: null,
  ...over,
});

function renderBlock(slugs: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ReviewLimitsBlock slugs={slugs} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApi.mockReset();
  mockedApiGet.mockReset();
  mockedApiGet.mockResolvedValue({
    items: [
      row("click"),
      row("click_miniapp", { enabled: true, max_amount: "90000.00" }),
      row("payme"),
    ],
  });
});

it("shows only this provider's kassas, with the stored limit", async () => {
  renderBlock(["click", "click_miniapp"]);

  expect(await screen.findByText("click_miniapp")).toBeInTheDocument();
  expect(screen.getByText("click")).toBeInTheDocument();
  expect(screen.queryByText("payme")).not.toBeInTheDocument();
  expect(
    screen.getByLabelText("Больше, сум", { selector: "#limit-click_miniapp-amount" }),
  ).toHaveValue("90000");
});

it("saves a changed limit with an idempotency key", async () => {
  mockedApi.mockResolvedValue(row("click_miniapp", { enabled: true, max_amount: "80000.00" }));
  renderBlock(["click_miniapp"]);

  const amount = await screen.findByLabelText("Больше, сум");
  fireEvent.change(amount, { target: { value: "80 000" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

  await waitFor(() => {
    expect(mockedApi).toHaveBeenCalledTimes(1);
  });
  const [path, init] = mockedApi.mock.calls[0] ?? [];
  expect(path).toBe("/api/v1/admin/payments/review-limits/click_miniapp");
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({
    enabled: true,
    max_amount: "80000",
    window_hours: 24,
  });
  expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
});
