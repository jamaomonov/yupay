import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { FulfillmentPage } from "./FulfillmentPage";

import type { TaskAdminOut } from "./types";

import { apiGet } from "@/lib/api";

/**
 * The inbox used to hand the operator a 50-row page carrying every task's
 * whole attempt log, then render the opened task's log below the pagination —
 * so clicking a row threw them to the bottom of the document, and a task with
 * 1641 status polls made that a very long way down.
 */

vi.mock("@/lib/api", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

const mockedApiGet = vi.mocked(apiGet);

function makeTask(over: Partial<TaskAdminOut> = {}): TaskAdminOut {
  return {
    id: "task-1",
    order_id: "019ffaea-0000-0000-0000-000000000000",
    order_item_id: "019ffaea-1111-1111-1111-111111111111",
    supplier: "waxpeer",
    status: "succeeded",
    attempts_count: 1641,
    last_error: null,
    external_order_id: null,
    admin_note: null,
    completed_by: null,
    extra_metadata: {},
    created_at: "2026-08-13T11:38:00Z",
    succeeded_at: "2026-08-14T14:59:00Z",
    failed_at: null,
    cancelled_at: null,
    ...over,
  };
}

/** Routes each call by URL so a test can assert what the page asked for. */
function mockApi(tasks: TaskAdminOut[], attemptsTotal = 1641) {
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/attempts")) {
      const limit = Number(new URLSearchParams(path.split("?")[1] ?? "").get("limit") ?? "25");
      return Promise.resolve({
        items: Array.from({ length: Math.min(limit, attemptsTotal) }, (_, i) => ({
          task_id: "task-1",
          supplier: "waxpeer",
          kind: "status_check",
          status: "ok",
          payload: { outcome: "in_progress" },
          error: null,
          created_at: `2026-08-14T10:${String(i).padStart(2, "0")}:00Z`,
        })),
        total: attemptsTotal,
      });
    }
    return Promise.resolve({ items: tasks, total: tasks.length });
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FulfillmentPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
});

it("fetches the attempt log only when a task is opened, and only that task's", async () => {
  mockApi([makeTask()]);
  renderPage();

  await screen.findByText("waxpeer");
  expect(mockedApiGet.mock.calls.some(([p]) => p.includes("/attempts"))).toBe(false);

  fireEvent.click(screen.getByText("waxpeer"));

  await waitFor(() => {
    const call = mockedApiGet.mock.calls.find(([p]) => p.includes("/attempts"));
    expect(call?.[0]).toContain("task_id=task-1");
  });
});

it("caps the log instead of rendering all 1641 rows", async () => {
  mockApi([makeTask()]);
  renderPage();
  fireEvent.click(await screen.findByText("waxpeer"));

  // 25 rows on screen, and the count tells the operator what is behind them.
  await waitFor(() => {
    expect(screen.getAllByText("status_check")).toHaveLength(25);
  });
  expect(screen.getByText(/Лог обращений — 1641/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Показать ещё/ })).toBeInTheDocument();
});

it("drops the selection when a filter moves it out of the list", async () => {
  // The panel used to keep pointing at a row the new page no longer contains,
  // so it silently disappeared without anyone closing it.
  mockApi([makeTask()]);
  renderPage();
  fireEvent.click(await screen.findByText("waxpeer"));
  expect(await screen.findByText("Детали задачи")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Статус"), { target: { value: "failed" } });

  await waitFor(() => {
    expect(screen.queryByText("Детали задачи")).not.toBeInTheDocument();
  });
});

it("names the column after what it counts, not after failures", async () => {
  mockApi([makeTask()]);
  renderPage();

  // 1641 under a header reading "Попыток" reads as a task retried into the
  // ground; it is one delivery plus a day of status polls.
  expect(await screen.findByText("Обращений")).toBeInTheDocument();
  expect(screen.queryByText("Попыток")).not.toBeInTheDocument();
});
