import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { FailedAutomaticTab } from "./FailedAutomaticTab";

import type { TaskAdminOut } from "./types";

import { apiGet, apiPost } from "@/lib/api";

/**
 * Moving a failed task onto another supplier has existed in the API and in
 * `TaskDetailPanel` since the second-channel work, but the panel only ever
 * rendered on the «Все» tab. An operator following the Failed badge — the
 * whole point of the inbox — therefore could not reach the one control that
 * answers "the supplier refused, send it somewhere else".
 */

vi.mock("@/lib/api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

function makeFailed(over: Partial<TaskAdminOut> = {}): TaskAdminOut {
  return {
    id: "task-1",
    order_id: "019ffaea-0000-0000-0000-000000000000",
    order_item_id: "019ffaea-1111-1111-1111-111111111111",
    supplier: "nova",
    status: "failed",
    attempts_count: 3,
    last_error: "nova refunded the order (refund)",
    external_order_id: null,
    admin_note: null,
    completed_by: null,
    extra_metadata: {},
    created_at: "2026-09-19T22:00:00Z",
    succeeded_at: null,
    failed_at: "2026-09-19T22:05:22Z",
    cancelled_at: null,
    ...over,
  };
}

function renderTab(tasks: TaskAdminOut[]) {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/attempts")) return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve({ items: tasks, total: tasks.length });
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FailedAutomaticTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
});

it("offers the supplier switch on the tab the failure is reported on", async () => {
  renderTab([makeFailed()]);

  const open = await screen.findByRole("button", { name: "Другой поставщик" });
  fireEvent.click(open);

  // The panel's own control, not merely a link somewhere else. The row
  // action is named differently from the panel's confirm button on purpose:
  // two buttons reading "Сменить поставщика" on one screen is a coin toss.
  await screen.findByLabelText("Новый поставщик");
});

it("moves the task onto the chosen supplier", async () => {
  mockedApiPost.mockResolvedValue({ ...makeFailed(), supplier: "g2b", status: "pending" });
  renderTab([makeFailed()]);

  fireEvent.click(await screen.findByRole("button", { name: "Другой поставщик" }));
  await screen.findByLabelText("Новый поставщик");
  fireEvent.click(screen.getByRole("button", { name: "Сменить поставщика" }));

  await waitFor(() => {
    const call = mockedApiPost.mock.calls.find(([p]) => p.includes("/reassign"));
    expect(call?.[0]).toContain("/tasks/task-1/reassign");
  });
});

it("keeps the low-balance shortcut beside it", async () => {
  renderTab([makeFailed({ last_error: "supplier_low_balance" })]);

  await screen.findByRole("button", { name: "Завершить вручную" });
  await screen.findByRole("button", { name: "Другой поставщик" });
});

/**
 * Reported from production 2026-09-20: two Dodsonshop Steam tasks sat in the
 * Failed tab for orders NOVA had already refunded. Both buttons on those rows
 * answer `409 deposit_already_returned`, so the inbox was showing work that
 * could never be done. The task is left `failed` deliberately — the refund
 * gates on that state — so the fix is the predicate, not the task.
 *
 * Each test below renders the settled row BESIDE an unsettled one and waits
 * for the unsettled row's checkbox before asserting. A bare
 * `waitFor(() => expect(...).not.toBeInTheDocument())` passes on the first
 * tick, while the list is still loading and nothing is on screen — the first
 * version of this test did exactly that and passed against the unfixed
 * predicate.
 */
it("drops a task whose merchant deposit has already been returned", async () => {
  renderTab([
    makeFailed({ id: "task-settled", deposit_settled: true }),
    makeFailed({ id: "task-open", deposit_settled: false }),
  ]);

  // The list has rendered once this is on screen.
  await screen.findByLabelText("Выбрать task-ope");
  expect(screen.queryByLabelText("Выбрать task-set")).not.toBeInTheDocument();
});

it("still shows a failure nobody has settled", async () => {
  // The other half of the pair: over-filtering would empty the operator's
  // queue, which is a worse failure than the noise it replaces.
  renderTab([makeFailed({ id: "task-open", deposit_settled: false })]);

  await screen.findByLabelText("Выбрать task-ope");
});

it("still shows a retail failure, which carries no deposit at all", async () => {
  // `deposit_settled` is absent on a retail row, not false — the predicate
  // must not read `undefined` as "settled".
  renderTab([makeFailed({ id: "task-retail", supplier: "g2b" })]);

  await screen.findByLabelText("Выбрать task-ret");
});
