import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { TaskDetailPanel } from "./TaskDetailPanel";

import type { TaskAdminOut } from "./types";

import { apiGet, apiPost } from "@/lib/api";

/**
 * The supplier a task was routed to errored, or our balance there ran dry,
 * and the operator wants *this* order out through the other channel. The
 * sourcing rule cannot do that — it governs orders not yet placed — so the
 * control lives on the task. What is pinned: it lists only the suppliers the
 * API says are mapped (cheapest preselected, with price and margin), posts to
 * `/reassign` with the chosen one, and is absent on a finished task.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

function task(over: Partial<TaskAdminOut> = {}): TaskAdminOut {
  return {
    id: "01a0b000-0000-7000-8000-000000000001",
    order_id: "01a0b000-0000-7000-8000-000000000002",
    order_item_id: "01a0b000-0000-7000-8000-000000000003",
    supplier: "waxpeer",
    status: "failed",
    attempts_count: 1,
    last_error: "WAXPEER_API_KEY is not configured",
    external_order_id: null,
    admin_note: null,
    completed_by: null,
    extra_metadata: {},
    created_at: "2026-09-16T10:00:00Z",
    succeeded_at: null,
    failed_at: "2026-09-16T10:00:05Z",
    cancelled_at: null,
    ...over,
  };
}

function renderPanel(t: TaskAdminOut) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TaskDetailPanel task={t} onClose={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockResolvedValue({ items: [], total: 0 });
});

const OPTIONS = {
  sku_id: "s1",
  sku_code: "pubgm-60",
  price_usd: "1.00",
  options: [
    { supplier: "gengine", cost_usdt: "0.85", cost_reason: null, stock: 12, reserve: false },
    { supplier: "g2b", cost_usdt: "0.92", cost_reason: null, stock: null, reserve: false },
    {
      supplier: "nova",
      cost_usdt: null,
      cost_reason: "нет в каталоге",
      stock: null,
      reserve: true,
    },
  ],
};

function routeGets() {
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(url.includes("reassign-options") ? OPTIONS : { items: [], total: 0 }),
  );
}

it("lists only the mapped suppliers, cheapest preselected, with price and margin", async () => {
  routeGets();
  renderPanel(task());

  const group = await screen.findByRole("radiogroup", { name: "Новый поставщик" });
  const radios = Array.from(group.querySelectorAll("input[type=radio]")).map((r) =>
    r.getAttribute("value"),
  );
  expect(radios).toEqual(["gengine", "g2b", "nova"]);
  expect(screen.getByText("$0.85")).toBeInTheDocument();
  expect(screen.getByText("маржа 15.0%")).toBeInTheDocument();
  expect(screen.getByText(/цена неизвестна — нет в каталоге/)).toBeInTheDocument();
  expect(group.querySelector<HTMLInputElement>("input[value=gengine]")?.checked).toBe(true);
});

it("moves the task to the supplier the operator picks", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  routeGets();
  mockedApiPost.mockResolvedValue(task({ supplier: "g2b", status: "pending" }));
  renderPanel(task());

  const group = await screen.findByRole("radiogroup", { name: "Новый поставщик" });
  const g2b = group.querySelector<HTMLInputElement>("input[value=g2b]");
  expect(g2b).not.toBeNull();
  if (g2b) fireEvent.click(g2b);
  fireEvent.click(screen.getByRole("button", { name: "Сменить поставщика" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/fulfillment/tasks/01a0b000-0000-7000-8000-000000000001/reassign",
      { supplier: "g2b" },
    );
  });
  confirm.mockRestore();
});

it("says so when no other supplier is mapped", async () => {
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes("reassign-options") ? { ...OPTIONS, options: [] } : { items: [], total: 0 },
    ),
  );
  renderPanel(task());
  expect(await screen.findByText(/нет маппинга у других поставщиков/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Сменить поставщика" })).not.toBeInTheDocument();
});

it("offers no move on a task that already finished", async () => {
  renderPanel(task({ status: "succeeded", succeeded_at: "2026-09-16T10:01:00Z", failed_at: null }));

  await screen.findByText("Детали задачи");
  expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Сменить поставщика" })).not.toBeInTheDocument();
});
