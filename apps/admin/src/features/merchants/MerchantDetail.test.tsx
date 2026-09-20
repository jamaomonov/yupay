// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { MerchantDetail } from "./MerchantDetail";

import type { DepositCreditOut, MerchantListOut, MerchantTxnListOut } from "./api";

import { apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

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
      id: "m1",
      title: "Pilot Reseller",
      status: "active",
      created_at: "2026-09-01T10:00:00Z",
      deposit_balance: "25.00",
    },
  ],
};

const TXNS: MerchantTxnListOut = {
  items: [
    {
      transaction_id: "t1",
      kind: "merchant_deposit_credit",
      amount: "25.00",
      note: "first top-up",
      actor: "admin:a1",
      created_at: "2026-09-01T11:00:00Z",
    },
  ],
};

function renderPage(qc?: QueryClient) {
  qc ??= new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/merchants/m1"]}>
        <Routes>
          <Route path="/merchants/:id" element={<MerchantDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedApiGet.mockReset();
  mockedApiPost.mockReset();
  mockedApiGet.mockImplementation((path: string) =>
    Promise.resolve(path.includes("/transactions") ? TXNS : LIST),
  );
});

async function typeAmountAndSubmit(amount: string, orderId?: string) {
  fireEvent.change(await screen.findByLabelText("Сумма (USD)"), { target: { value: amount } });
  if (orderId !== undefined) {
    fireEvent.change(screen.getByLabelText(/ID заказа/), { target: { value: orderId } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Зачислить" }));
}

/** A settlement's order id, as an operator pastes it out of `orders.id`. */
const ORDER = "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34";

it("shows the balance, the ledger and the credited note", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "Pilot Reseller" })).toBeInTheDocument();
  expect(screen.getByText("$25.00")).toBeInTheDocument();
  expect(await screen.findByText("«first top-up»")).toBeInTheDocument();
  expect(screen.getByText("+$25.00")).toBeInTheDocument();
});

it("freezing asks for confirmation and only then posts", async () => {
  mockedApiPost.mockResolvedValue({ ...LIST.items[0], status: "frozen" });
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Заморозить" }));
  // Nothing posted yet — the dialog with the exact action is up first.
  expect(mockedApiPost).not.toHaveBeenCalled();

  fireEvent.click(await screen.findByRole("button", { name: "Да, заморозить" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledWith(
      "/api/v1/admin/merchants/m1/freeze",
      {},
      expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
    );
  });
});

it("credits the deposit and shows the balance from the response", async () => {
  const result: DepositCreditOut = {
    transaction_id: "t2",
    merchant_id: "m1",
    amount: "10.00",
    balance: "35.00",
    order_id: null,
  };
  mockedApiPost.mockResolvedValue(result);
  renderPage();

  await typeAmountAndSubmit("10");
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [url, body, headers] = mockedApiPost.mock.calls[0] ?? [];
  expect(url).toBe("/api/v1/admin/merchants/m1/deposit-credits");
  expect(body).toEqual({ amount: "10", note: null, order_id: null });
  expect(headers).toEqual(
    expect.objectContaining({ "Idempotency-Key": expect.any(String) as string }),
  );

  // The RESPONSE balance is what gets shown — not client-side math.
  expect(await screen.findByText("Баланс после зачисления: $35.00")).toBeInTheDocument();
});

it("warns loudly when a replayed key booked a different amount", async () => {
  // Operator typed 99 but the key had already booked 10.00 — the endpoint
  // replays the ORIGINAL transaction and the UI must make that visible.
  mockedApiPost.mockResolvedValue({
    transaction_id: "t-old",
    merchant_id: "m1",
    amount: "10.00",
    balance: "35.00",
  });
  renderPage();

  await typeAmountAndSubmit("99");
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("$10.00");
  expect(alert.textContent).toContain("$99.00");
  expect(alert.textContent).toContain("по ранее использованному ключу");
});

it("ignores a double-click while the credit is in flight", async () => {
  let resolveCredit: (v: DepositCreditOut) => void = () => undefined;
  mockedApiPost.mockImplementation(
    () =>
      new Promise<DepositCreditOut>((resolve) => {
        resolveCredit = resolve;
      }),
  );
  renderPage();

  await typeAmountAndSubmit("10");
  const confirm = await screen.findByRole("button", { name: "Да, зачислить" });
  // Three same-tick clicks: the in-flight ref flips synchronously, so only
  // the first one reaches the mutation.
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  fireEvent.click(confirm);

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  resolveCredit({
    transaction_id: "t2",
    merchant_id: "m1",
    amount: "10.00",
    balance: "35.00",
    order_id: null,
  });
  await waitFor(() => {
    expect(screen.getByText("Баланс после зачисления: $35.00")).toBeInTheDocument();
  });
  expect(mockedApiPost).toHaveBeenCalledTimes(1);
});

it("mints a fresh idempotency key for a new attempt but keeps it across a retry", async () => {
  mockedApiPost
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce({
      transaction_id: "t2",
      merchant_id: "m1",
      amount: "10.00",
      balance: "35.00",
    })
    .mockResolvedValueOnce({
      transaction_id: "t3",
      merchant_id: "m1",
      amount: "5.00",
      balance: "40.00",
    });
  renderPage();

  // Attempt 1: first confirm click fails, the dialog stays; retry reuses the key.
  await typeAmountAndSubmit("10");
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  fireEvent.click(screen.getByRole("button", { name: "Да, зачислить" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(2);
  });

  // Attempt 2 (new submit) gets a NEW key.
  await typeAmountAndSubmit("5");
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));
  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(3);
  });

  const keyOf = (call: unknown[]): unknown =>
    (call[2] as Record<string, string> | undefined)?.["Idempotency-Key"];
  const [first, second, third] = mockedApiPost.mock.calls;
  expect(keyOf(first ?? [])).toBeDefined();
  expect(keyOf(second ?? [])).toBe(keyOf(first ?? []));
  expect(keyOf(third ?? [])).not.toBe(keyOf(first ?? []));
});

it("keeps the spinner up instead of flashing «не найден» while the list refetches", async () => {
  // The moment right after a create: navigation lands on a cache that does
  // not carry the merchant yet while the invalidated list refetch is still
  // in flight. A settled list may say "not found"; an in-flight one may not.
  let resolveList: (v: MerchantListOut) => void = () => undefined;
  mockedApiGet.mockImplementation((path: string) => {
    if (path.includes("/transactions")) return Promise.resolve(TXNS);
    return new Promise<MerchantListOut>((resolve) => {
      resolveList = resolve;
    });
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(qk.merchants(), { items: [] });
  renderPage(qc);

  expect(screen.queryByText("Мерчант не найден.")).not.toBeInTheDocument();
  expect(screen.getByText("Загрузка…")).toBeInTheDocument();

  resolveList(LIST);
  expect(await screen.findByRole("heading", { name: "Pilot Reseller" })).toBeInTheDocument();
});

// ---------- settling one failed order (M3b Task 2) ----------

it("sends the order id so the credit lands on that order's refunded_usd", async () => {
  const result: DepositCreditOut = {
    transaction_id: "t2",
    merchant_id: "m1",
    amount: "1.07",
    balance: "26.07",
    order_id: ORDER,
  };
  mockedApiPost.mockResolvedValue(result);
  renderPage();

  await typeAmountAndSubmit("1.07", ORDER);
  // The confirm names the order, because attributing is what makes the
  // credit visible to the merchant and it cannot be changed afterwards.
  expect(await screen.findByText(new RegExp(ORDER))).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [, body] = mockedApiPost.mock.calls[0] ?? [];
  expect(body).toEqual({ amount: "1.07", note: null, order_id: ORDER });

  // The attribution is echoed back from the RESPONSE, not from what was typed.
  expect(await screen.findByText(`Привязано к заказу ${ORDER}`)).toBeInTheDocument();
});

it("canonicalises the order id the way the API does", async () => {
  mockedApiPost.mockResolvedValue({
    transaction_id: "t2",
    merchant_id: "m1",
    amount: "1.07",
    balance: "26.07",
    order_id: ORDER,
  });
  renderPage();

  // `Guid.ToString("B")` in .NET, upper-cased, with stray whitespace: all
  // spellings Python's `UUID()` accepts, and none of them what Postgres does.
  await typeAmountAndSubmit("1.07", `  {${ORDER.toUpperCase()}}  `);
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
  const [, body] = mockedApiPost.mock.calls[0] ?? [];
  expect(body).toEqual({ amount: "1.07", note: null, order_id: ORDER });
});

it("refuses an order id that is not a UUID without posting anything", async () => {
  renderPage();
  // A merchant_order_id is the id an operator will reach for by mistake, and
  // the API would answer 404 — which reads as "no such order", not "wrong id".
  await typeAmountAndSubmit("1.07", "acme-2026-000417");

  expect(mockedApiPost).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Да, зачислить" })).not.toBeInTheDocument();
});

it("warns loudly when a replayed key booked the credit against another order", async () => {
  // The attribution cannot be repaired afterwards — a replay returns the
  // ORIGINAL transaction and no surface can re-point one.
  mockedApiPost.mockResolvedValue({
    transaction_id: "t-old",
    merchant_id: "m1",
    amount: "1.07",
    balance: "26.07",
    order_id: "0198c000-0000-7000-8000-000000000000",
  });
  renderPage();

  await typeAmountAndSubmit("1.07", ORDER);
  fireEvent.click(await screen.findByRole("button", { name: "Да, зачислить" }));

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("0198c000-0000-7000-8000-000000000000");
  expect(alert.textContent).toContain(ORDER);
  expect(screen.queryByText(`Привязано к заказу ${ORDER}`)).not.toBeInTheDocument();
});

// ---------- debiting the deposit ----------
//
// The control the page was missing: an operator typed `−1` into «Пополнить
// депозит» and got "сумма должна быть положительной". The endpoint existed;
// the button did not.

async function debitAndConfirm(amount: string, reason: string) {
  fireEvent.change(await screen.findByLabelText("Сумма списания (USD)"), {
    target: { value: amount },
  });
  fireEvent.change(screen.getByLabelText(/Причина/), { target: { value: reason } });
  fireEvent.click(screen.getByRole("button", { name: "Списать" }));
  fireEvent.click(await screen.findByRole("button", { name: "Да, списать" }));
}

it("debits the deposit and shows the balance from the response", async () => {
  mockedApiPost.mockResolvedValue({
    transaction_id: "t9",
    merchant_id: "m1",
    amount: "4.00",
    balance: "21.00",
  });
  renderPage();

  await debitAndConfirm("4", "ошибочное пополнение");

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalled();
  });
  const [url, body] = mockedApiPost.mock.calls[0] ?? [];
  expect(url).toBe("/api/v1/admin/merchants/m1/deposit-debits");
  expect(body).toEqual({ amount: "4", reason: "ошибочное пополнение" });
  // The balance shown is the API's, never the form's arithmetic.
  expect(await screen.findByText(/\$21\.00/)).toBeInTheDocument();
});

it("refuses a debit with no reason without posting anything", async () => {
  renderPage();

  fireEvent.change(await screen.findByLabelText("Сумма списания (USD)"), {
    target: { value: "4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Списать" }));

  // The ledger row is the only record of why a balance fell, so the form
  // must not let one through without it. Asserted the way the credit tests
  // beside it do — no request, and the confirm dialog never opens (toasts
  // are not rendered in this harness).
  expect(mockedApiPost).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Да, списать" })).not.toBeInTheDocument();
});

it("refuses to debit more than the balance without posting anything", async () => {
  renderPage();

  fireEvent.change(await screen.findByLabelText("Сумма списания (USD)"), {
    target: { value: "25.01" },
  });
  fireEvent.change(screen.getByLabelText(/Причина/), { target: { value: "перебор" } });
  fireEvent.click(screen.getByRole("button", { name: "Списать" }));

  // The server answers 409 anyway; catching it here means the confirm dialog
  // never opens on an amount that cannot work.
  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "Да, списать" })).not.toBeInTheDocument();
  });
  expect(mockedApiPost).not.toHaveBeenCalled();
});

it("fills the whole balance in one click", async () => {
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Весь остаток" }));

  expect(await screen.findByLabelText("Сумма списания (USD)")).toHaveValue("25.00");
});

it("names the remaining balance in the confirmation, not just the amount", async () => {
  renderPage();

  fireEvent.change(await screen.findByLabelText("Сумма списания (USD)"), {
    target: { value: "4" },
  });
  fireEvent.change(screen.getByLabelText(/Причина/), { target: { value: "коррекция" } });
  fireEvent.click(screen.getByRole("button", { name: "Списать" }));

  // "How much will be left" is the number the operator is deciding on.
  expect(await screen.findByText(/Останется \$21\.00/)).toBeInTheDocument();
});

it("warns when a replayed key booked a different amount", async () => {
  mockedApiPost.mockResolvedValue({
    transaction_id: "t9",
    merchant_id: "m1",
    amount: "2.00",
    balance: "23.00",
  });
  renderPage();

  await debitAndConfirm("4", "коррекция");

  // The ledger replays by key without comparing parameters. The observable
  // difference from a clean success: the form is NOT cleared, so the operator
  // still sees what they typed beside a balance that moved by something else.
  // (Toasts are not rendered in this harness — same as the credit tests.)
  await waitFor(() => {
    expect(screen.getByText(/\$23\.00/)).toBeInTheDocument();
  });
  expect(screen.getByLabelText("Сумма списания (USD)")).toHaveValue("4");
});

it("ignores a double-click while the debit is in flight", async () => {
  mockedApiPost.mockImplementation(
    () =>
      new Promise((resolve) => {
        setTimeout(() => {
          resolve({ transaction_id: "t9", merchant_id: "m1", amount: "4.00", balance: "21.00" });
        }, 50);
      }),
  );
  renderPage();

  fireEvent.change(await screen.findByLabelText("Сумма списания (USD)"), {
    target: { value: "4" },
  });
  fireEvent.change(screen.getByLabelText(/Причина/), { target: { value: "коррекция" } });
  fireEvent.click(screen.getByRole("button", { name: "Списать" }));
  const confirm = await screen.findByRole("button", { name: "Да, списать" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);

  await waitFor(() => {
    expect(mockedApiPost).toHaveBeenCalledTimes(1);
  });
});
