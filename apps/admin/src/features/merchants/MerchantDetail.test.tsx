// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { MerchantDetail } from "./MerchantDetail";

import type { DepositCreditOut, MerchantListOut, MerchantTxnListOut } from "./api";

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

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

async function typeAmountAndSubmit(amount: string) {
  fireEvent.change(await screen.findByLabelText("Сумма (USD)"), { target: { value: amount } });
  fireEvent.click(screen.getByRole("button", { name: "Зачислить" }));
}

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
  expect(body).toEqual({ amount: "10", note: null });
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
  resolveCredit({ transaction_id: "t2", merchant_id: "m1", amount: "10.00", balance: "35.00" });
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
