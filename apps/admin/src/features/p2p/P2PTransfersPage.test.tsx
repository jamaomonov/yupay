// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { P2PTransfersPage } from "./P2PTransfersPage";

import type { P2PIncoming } from "./api";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const get = vi.mocked(apiGet);

const base: P2PIncoming = {
  id: "i1",
  received_at: "2026-10-04T10:00:00Z",
  bank_time: "2026-10-04T10:00:00Z",
  kind: "credit",
  amount_uzs: "50001",
  source_text: null,
  card_last4: "3311",
  balance_after: null,
  chain_ok: true,
  result: "unmatched",
  reservation: null,
};
const ROWS: P2PIncoming[] = [
  base,
  {
    ...base,
    id: "i2",
    result: "matched",
    reservation: { number: "P-1", merchant_id: "m1", merchant_title: "Acme", amount_usd: "4.00" },
  },
];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <P2PTransfersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  get.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("/incoming/i1")
        ? { ...base, raw_text: "RAW NOTIFICATION" }
        : { items: ROWS, next_cursor: null },
    ),
  );
});

it("labels unmatched rows and links matched ones to the merchant", async () => {
  renderPage();
  const link = await screen.findByRole("link", { name: "Acme" });
  expect(link).toHaveAttribute("href", "/merchants/m1");
  // The same label is also a filter option; the table cell is the one in a row.
  const cell = within(screen.getByRole("table")).getByText("Не сопоставлено");
  expect(cell).toBeInTheDocument();
});

it("opens the raw notification text in a pre block on row click", async () => {
  renderPage();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.click(within(screen.getByRole("table")).getByText("Не сопоставлено"));
  const pre = await screen.findByText("RAW NOTIFICATION");
  expect(pre.tagName).toBe("PRE");
});

it("shows the reservations tab", async () => {
  get.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("/reservations")
        ? {
            items: [
              {
                number: "P-9",
                merchant_id: null,
                merchant_title: null,
                card_last4: "3311",
                amount_uzs: 50001,
                amount_usd: "4.00",
                status: "paid",
                created_at: "2026-10-04T10:00:00Z",
                expires_at: "2026-10-04T10:05:00Z",
                closed_at: null,
              },
            ],
            next_cursor: null,
          }
        : { items: [], next_cursor: null },
    ),
  );
  renderPage();
  fireEvent.click(screen.getByRole("tab", { name: "Резервы" }));
  expect(await screen.findByText("P-9")).toBeInTheDocument();
  expect(within(screen.getByRole("table")).getByText("Оплачен")).toBeInTheDocument();
});

const incomingCalls = () =>
  get.mock.calls.map(([p]) => p).filter((p) => /\/incoming(\?|$)/.test(p));

it("applies journal filters only on apply, sending them as query params", async () => {
  renderPage();
  await screen.findByRole("link", { name: "Acme" });
  const before = get.mock.calls.length;
  fireEvent.change(screen.getByRole("combobox", { name: "Тип" }), { target: { value: "credit" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Результат" }), {
    target: { value: "matched" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Карта" }), { target: { value: "3311" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Сумма" }), { target: { value: "50001" } });
  expect(get.mock.calls.length).toBe(before);
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await waitFor(() => {
    expect(incomingCalls().length).toBeGreaterThan(0);
  });
  const url = new URL(incomingCalls().at(-1) ?? "", "http://x");
  expect(url.searchParams.get("card_last4")).toBe("3311");
  expect(url.searchParams.get("kind")).toBe("credit");
  expect(url.searchParams.get("result")).toBe("matched");
  expect(url.searchParams.get("amount")).toBe("50001");
});

it("resets the filters", async () => {
  renderPage();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.change(screen.getByRole("textbox", { name: "Карта" }), { target: { value: "3311" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await waitFor(() => {
    expect(incomingCalls().some((p) => p.includes("card_last4=3311"))).toBe(true);
  });
  fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
  await waitFor(() => {
    expect(incomingCalls().at(-1)).not.toContain("card_last4");
  });
  expect(screen.getByRole("textbox", { name: "Карта" })).toHaveValue("");
});

it("loads more with the previous page's cursor and appends rows", async () => {
  get.mockImplementation((path: string) => {
    if (path.includes("cursor=c2")) {
      return Promise.resolve({
        items: [{ ...base, id: "i3", result: "unmatched", amount_uzs: "77777" }],
        next_cursor: null,
      });
    }
    return Promise.resolve({ items: ROWS, next_cursor: "c2" });
  });
  renderPage();
  await screen.findByRole("link", { name: "Acme" });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить ещё" }));
  expect(await screen.findByText(/77\s?777/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Acme" })).toBeInTheDocument();
  expect(incomingCalls().at(-1)).toContain("cursor=c2");
});
