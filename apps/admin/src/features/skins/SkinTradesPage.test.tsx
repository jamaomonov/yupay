// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinTradesPage } from "./SkinTradesPage";

import type { AdminSkinTradeOut, AdminSkinTradesOut } from "./api";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockedApiGet = vi.mocked(apiGet);
const mockedApiPost = vi.mocked(apiPost);

const ROW: AdminSkinTradeOut = {
  id: "t1",
  project_id: "p-key-1",
  waxpeer_id: 77,
  order_id: "01a0e987-eede-7d40-892f-fe7f3b3bd0e9",
  order_item_id: "i1",
  created_at: "2026-09-29T10:00:00Z",
  market_hash_name: "AK-47 | Redline (Field-Tested)",
  phase: "",
  image_url: null,
  sold_usd: "30.00",
  paid_units: 27867,
  bought_units: 27000,
  waxpeer_status: 6,
  state: "failed",
  reason_code: "other",
  reason: "rollback",
  penalties: { total_penalty: 1500 },
  seller_name: "darpan6awx",
  trade_id: "9393511289",
  offer_url: "https://steamcommunity.com/tradeoffer/9393511289/",
  send_until: null,
  release_date: "2026-10-05T16:00:00Z",
  accepted_at: "2026-09-28T16:00:00Z",
  last_checked_at: null,
  task_id: "task-1",
  task_status: "succeeded",
  task_sub_state: null,
  refunded_to: null,
  can_refund: false,
  can_retry: false,
  resolved_at: null,
  resolved_note: null,
  attention: true,
};

const PAGE: AdminSkinTradesOut = { total: 1, items: [ROW], counts: { active: 3, attention: 1 } };

function renderPage(entry = "/skins/trades") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/skins/trades" element={<SkinTradesPage />} />
          <Route path="/orders/:id" element={<div>order-stub</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const table = () => screen.getByRole("table");

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockResolvedValue(PAGE);
});

it("says why in words and dollars, and shows the margin", async () => {
  renderPage();
  await screen.findByRole("table");
  expect(within(table()).getByText(/Откат после доставки/)).toBeInTheDocument();
  expect(within(table()).getByText(/штраф \$1\.50/)).toBeInTheDocument();
  expect(within(table()).getByText("$27.00")).toBeInTheDocument();
  expect(within(table()).getByText(/\$3\.00/)).toBeInTheDocument();
  expect(within(table()).queryByText("rollback")).not.toBeInTheDocument();
});

it("counts what is in flight and what needs a human on the tabs", async () => {
  renderPage();
  expect(await screen.findByRole("tab", { name: /В процессе\s*3/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Требуют внимания\s*1/ })).toBeInTheDocument();
});

it("asks for the trades needing a human on that tab", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("tab", { name: /Требуют внимания/ }));
  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => p.includes("view=attention"))).toBe(true);
  });
});

it("opens the trade's details — Waxpeer keys, Steam link, the order", async () => {
  renderPage();
  await screen.findByRole("table");
  fireEvent.click(within(table()).getByText("AK-47 | Redline (Field-Tested)"));
  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getByText("p-key-1")).toBeInTheDocument();
  expect(within(drawer).getByRole("link", { name: /Обмен в Steam/ })).toHaveAttribute(
    "href",
    "https://steamcommunity.com/tradeoffer/9393511289/",
  );
  fireEvent.click(within(drawer).getByRole("link", { name: "Открыть заказ" }));
  expect(await screen.findByText("order-stub")).toBeInTheDocument();
});

it("resolves from the details with a note", async () => {
  mockedApiPost.mockResolvedValue({ ...ROW, resolved_at: "2026-09-29T12:00:00Z" });
  renderPage();
  await screen.findByRole("table");
  fireEvent.click(within(table()).getByText("AK-47 | Redline (Field-Tested)"));
  const drawer = await screen.findByRole("dialog");
  fireEvent.change(within(drawer).getByRole("textbox"), {
    target: { value: "вернули на баланс" },
  });
  fireEvent.click(within(drawer).getByRole("button", { name: "Отметить разобранным" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [path, body, headers] = mockedApiPost.mock.calls[0]!;
  expect(path).toBe("/api/v1/admin/skins/trades/t1/resolve");
  expect(body).toEqual({ note: "вернули на баланс" });
  expect(headers).toEqual(expect.objectContaining({ "Idempotency-Key": expect.any(String) }));
});

it("searches once the operator stops typing, not per keystroke", async () => {
  renderPage();
  const box = await screen.findByRole("searchbox");
  fireEvent.change(box, { target: { value: "a" } });
  fireEvent.change(box, { target: { value: "ak" } });
  await waitFor(() => {
    expect(mockedApiGet.mock.calls.some(([p]) => p.endsWith("q=ak"))).toBe(true);
  });
  expect(mockedApiGet.mock.calls.some(([p]) => p.endsWith("q=a"))).toBe(false);
});

it("says so when there are none", async () => {
  mockedApiGet.mockResolvedValue({ total: 0, items: [], counts: { active: 0, attention: 0 } });
  renderPage();
  expect(await screen.findByText("Обменов нет")).toBeInTheDocument();
});

it("writes a loss with a minus before the dollar", async () => {
  mockedApiGet.mockResolvedValue({
    ...PAGE,
    items: [{ ...ROW, sold_usd: "20.00", bought_units: 27000 }],
  });
  renderPage();
  await screen.findByRole("table");
  expect(within(table()).getByText(/−\$7\.00/)).toBeInTheDocument();
});

it("names a Waxpeer balance shortfall and that the customer got the money back", async () => {
  mockedApiGet.mockResolvedValue({
    ...PAGE,
    items: [
      {
        ...ROW,
        waxpeer_status: null,
        reason_code: "try_later",
        reason: "supplier_low_balance",
        penalties: null,
        task_status: "failed",
      },
    ],
  });
  renderPage();
  await screen.findByRole("table");
  expect(within(table()).getByText(/Не хватило баланса Waxpeer/)).toBeInTheDocument();
  expect(within(table()).queryByText("supplier_low_balance")).not.toBeInTheDocument();
});

async function openDrawer(row: AdminSkinTradeOut) {
  mockedApiGet.mockResolvedValue({ ...PAGE, items: [row] });
  renderPage();
  await screen.findByRole("table");
  fireEvent.click(within(table()).getByText("AK-47 | Redline (Field-Tested)"));
  return screen.findByRole("dialog");
}

it("refunds to the balance from the details, after a confirm", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  mockedApiPost.mockResolvedValue({ ...ROW, refunded_to: "wallet" });
  const drawer = await openDrawer({ ...ROW, can_refund: true });
  fireEvent.click(within(drawer).getByRole("button", { name: "Вернуть деньги на баланс" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [path, , headers] = mockedApiPost.mock.calls[0]!;
  expect(path).toBe("/api/v1/admin/skins/trades/t1/refund");
  expect(headers).toEqual(expect.objectContaining({ "Idempotency-Key": expect.any(String) }));
  expect(confirm).toHaveBeenCalled();
  confirm.mockRestore();
});

it("retries the task, warning to check Waxpeer first", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  mockedApiPost.mockResolvedValue({});
  const drawer = await openDrawer({ ...ROW, can_retry: true, task_status: "failed" });
  fireEvent.click(within(drawer).getByRole("button", { name: "Повторить покупку" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  expect(mockedApiPost.mock.calls[0]![0]).toBe("/api/v1/admin/fulfillment/tasks/task-1/retry");
  expect(confirm.mock.calls[0]![0]).toMatch(/p-key-1/);
  confirm.mockRestore();
});

it("offers neither when the money is back or the skin is on its way", async () => {
  const drawer = await openDrawer({ ...ROW, refunded_to: "wallet" });
  expect(within(drawer).queryByRole("button", { name: "Вернуть деньги на баланс" })).toBeNull();
  expect(within(drawer).queryByRole("button", { name: "Повторить покупку" })).toBeNull();
  expect(within(drawer).getByText(/Деньги вернули на баланс/)).toBeInTheDocument();
});
