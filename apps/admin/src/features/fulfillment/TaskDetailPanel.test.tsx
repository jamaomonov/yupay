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
 * control lives on the task. What is pinned: it posts to `/reassign` with the
 * chosen supplier, never offers the supplier the task is already on, and is
 * absent on a task that has finished, where moving it would buy twice.
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

it("moves a failed task to the supplier the operator picks", async () => {
  mockedApiPost.mockResolvedValue(task({ supplier: "gengine", status: "succeeded" }));
  renderPanel(task());

  const picker = await screen.findByLabelText("Новый поставщик");
  fireEvent.change(picker, { target: { value: "gengine" } });
  fireEvent.click(screen.getByRole("button", { name: "Сменить поставщика" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/fulfillment/tasks/01a0b000-0000-7000-8000-000000000001/reassign",
      { supplier: "gengine" },
    );
  });
});

it("never offers the supplier the task is already on", async () => {
  renderPanel(task({ supplier: "gengine" }));

  const picker = await screen.findByLabelText("Новый поставщик");
  const slugs = Array.from(picker.querySelectorAll("option")).map((o) => o.getAttribute("value"));
  expect(slugs).not.toContain("gengine");
  expect(slugs).toContain("waxpeer");
  expect(slugs).toContain("g2b");
  // Not the warehouse and not the manual queue — those have their own intakes.
  expect(slugs).not.toContain("inventory");
  expect(slugs).not.toContain("manual");
});

it("offers no move on a task that already finished", async () => {
  renderPanel(task({ status: "succeeded", succeeded_at: "2026-09-16T10:01:00Z", failed_at: null }));

  await screen.findByText("Детали задачи");
  expect(screen.queryByLabelText("Новый поставщик")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Сменить поставщика" })).not.toBeInTheDocument();
});
