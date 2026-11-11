// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { UsdtJournal } from "./UsdtJournal";

import type { UsdtIncoming } from "./api";

import { apiGet, apiPost } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const get = vi.mocked(apiGet);
const post = vi.mocked(apiPost);

const UNMATCHED: UsdtIncoming = {
  id: "u1",
  tx_id: "a".repeat(64),
  from_address: "TXsenderAddressxxxxxxxxxxxxxxxxxx1",
  amount_usdt: "25.129900",
  block_at: "2026-11-11T10:00:00Z",
  received_at: "2026-11-11T10:00:20Z",
  result: "unmatched",
  reservation_number: null,
  merchant_id: null,
  merchant_title: null,
  note: null,
  resolved_at: null,
};
const MATCHED: UsdtIncoming = {
  ...UNMATCHED,
  id: "u2",
  result: "matched",
  reservation_number: "U-7",
  merchant_id: "m1",
  merchant_title: "Acme",
};

function renderJournal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UsdtJournal />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  get.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("/admin/merchants")
        ? { items: [{ id: "m1", title: "Acme" }] }
        : { items: [UNMATCHED, MATCHED], next_cursor: null },
    ),
  );
});

it("links chain values to tronscan and the matched reseller to its page", async () => {
  renderJournal();
  const link = await screen.findByRole("link", { name: "Acme" });
  expect(link).toHaveAttribute("href", "/merchants/m1");
  const tx = screen.getAllByRole("link", { name: "aaaaaa…aaaa" })[0];
  expect(tx).toHaveAttribute("href", `https://tronscan.org/#/transaction/${"a".repeat(64)}`);
});

it("the unmatched quick filter queries result=unmatched", async () => {
  renderJournal();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.click(screen.getByRole("button", { name: "Неопознанные" }));
  await waitFor(() => {
    expect(get).toHaveBeenCalledWith("/api/v1/admin/usdt/incoming?result=unmatched");
  });
});

it("credits an unmatched transfer rounded down to cents, with an idempotency key", async () => {
  post.mockResolvedValue({ ...UNMATCHED, result: "manual", merchant_id: "m1" });
  renderJournal();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.click(screen.getByRole("button", { name: "Зачислить" }));
  const select = await screen.findByRole("combobox", { name: "Реселлер" });
  await within(select).findByRole("option", { name: "Acme" });
  fireEvent.change(select, { target: { value: "m1" } });
  const panel = screen.getByRole("complementary");
  fireEvent.click(within(panel).getByRole("button", { name: "Зачислить" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("$25.12");
  fireEvent.click(within(dialog).getByRole("button", { name: "Зачислить $25.12" }));
  await waitFor(() => {
    expect(post).toHaveBeenCalledWith(
      "/api/v1/admin/usdt/incoming/u1/credit",
      { merchant_id: "m1" },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
});

it("dismiss needs a note before it can be confirmed", async () => {
  post.mockResolvedValue({ ...UNMATCHED, result: "dismissed", note: "refunded" });
  renderJournal();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.click(screen.getByRole("button", { name: "Закрыть без зачисления" }));
  const panel = await screen.findByRole("complementary");
  const submit = within(panel).getByRole("button", { name: "Закрыть без зачисления" });
  expect(submit).toBeDisabled();
  fireEvent.change(within(panel).getByRole("textbox"), { target: { value: "refunded" } });
  fireEvent.click(submit);
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", { name: "Закрыть" }),
  );
  await waitFor(() => {
    expect(post).toHaveBeenCalledWith(
      "/api/v1/admin/usdt/incoming/u1/dismiss",
      { note: "refunded" },
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
});
