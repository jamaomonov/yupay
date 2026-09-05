// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OrderPayNow } from "./OrderPayNow";

import type * as ClientModule from "@/lib/client";
import type { PaymentOut } from "@/lib/orders-types";
import type * as PaymentReturnModule from "@/lib/payment-return";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/client";
import { AUTO_OPEN_PARAM, openAcquirer } from "@/lib/payment-return";

/**
 * The order page's half of the payment-return fix: it fetches the order's
 * live payment, offers «Оплатить» for one that is still payable, and — when
 * checkout pushed it here with the one-shot `?pay=1` flag — opens the
 * acquirer itself, exactly once.
 *
 * The looping failure this guards against is the whole reason the flag is
 * one-shot: the buyer finishes in the bank app, switches back to the browser,
 * and the tab must NOT throw them straight back into the bank app.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string) => k,
}));

const { pushMock, replaceMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  replaceMock: vi.fn(),
}));

// Mutable so a test can render the page as "just arrived from checkout"
// (`?pay=1`) or as "came back from the bank app" (flag already stripped).
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => "/orders/order-1",
  useSearchParams: () => searchParams,
}));

// Only the one function that would actually leave the page is stubbed — every
// pure helper stays real, so these tests exercise the shipped flag/payability
// logic rather than a re-declaration of it.
vi.mock("@/lib/payment-return", async (importOriginal) => ({
  ...(await importOriginal<typeof PaymentReturnModule>()),
  openAcquirer: vi.fn(),
}));

const mockApiFetch = vi.fn<(path: string, opts?: unknown) => Promise<unknown>>();
vi.mock("@/lib/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  apiFetch: (path: string, opts?: unknown) => mockApiFetch(path, opts),
}));

const openAcquirerMock = vi.mocked(openAcquirer);

afterEach(() => {
  vi.clearAllMocks();
  searchParams = new URLSearchParams();
  window.sessionStorage.clear();
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function payment(overrides: Partial<PaymentOut> = {}): PaymentOut {
  return {
    id: "pay-1",
    order_id: "order-1",
    provider: "uzum",
    status: "pending",
    amount: "45000.00",
    currency: "UZS",
    intent_url: "https://uzumbank.uz/open-service?id=1",
    external_id: "ext-1",
    ...overrides,
  };
}

function panel(props: Partial<Parameters<typeof OrderPayNow>[0]> = {}) {
  return (
    <OrderPayNow
      orderId="order-1"
      email={undefined}
      auth={undefined}
      awaitingPayment={true}
      {...props}
    />
  );
}

it("offers the pay button for a payment that is still payable", async () => {
  mockApiFetch.mockResolvedValue(payment());

  wrap(panel());

  const link = await screen.findByRole("link", { name: "payNow" });
  expect(link).toHaveAttribute("href", "https://uzumbank.uz/open-service?id=1");
  // No flag in the URL — nothing auto-opens, the buyer chooses.
  expect(openAcquirerMock).not.toHaveBeenCalled();
});

it("offers nothing for a payment that is over", async () => {
  mockApiFetch.mockResolvedValue(payment({ status: "cancelled" }));

  wrap(panel());

  await waitFor(() => {
    expect(mockApiFetch).toHaveBeenCalled();
  });
  expect(screen.queryByRole("link", { name: "payNow" })).not.toBeInTheDocument();
  expect(openAcquirerMock).not.toHaveBeenCalled();
});

it("offers nothing — and asks nothing — for an order past pending_payment", async () => {
  wrap(panel({ awaitingPayment: false }));

  await waitFor(() => {
    expect(screen.queryByRole("link", { name: "payNow" })).not.toBeInTheDocument();
  });
  expect(mockApiFetch).not.toHaveBeenCalled();
});

it("stays silent when there is no active payment (404)", async () => {
  mockApiFetch.mockRejectedValue(new ApiError(404, "/payments/by-order/order-1"));

  wrap(panel());

  await waitFor(() => {
    expect(mockApiFetch).toHaveBeenCalled();
  });
  expect(screen.queryByRole("link", { name: "payNow" })).not.toBeInTheDocument();
});

it("opens the acquirer once when checkout sent the buyer here with the flag", async () => {
  searchParams = new URLSearchParams(`${AUTO_OPEN_PARAM}=1`);
  mockApiFetch.mockResolvedValue(payment());

  const { rerender } = wrap(panel());

  await waitFor(() => {
    expect(openAcquirerMock).toHaveBeenCalledWith("https://uzumbank.uz/open-service?id=1");
  });
  expect(openAcquirerMock).toHaveBeenCalledTimes(1);
  // The flag is stripped from the URL the buyer comes back to.
  expect(replaceMock).toHaveBeenCalledWith("/orders/order-1", { scroll: false });

  // Re-renders (a poll landing, the WS pushing) must not re-open it.
  rerender(<QueryClientProvider client={new QueryClient()}>{panel()}</QueryClientProvider>);
  expect(openAcquirerMock).toHaveBeenCalledTimes(1);
});

it("does not re-open the acquirer when the buyer comes back from the bank app", async () => {
  // Coming back is a fresh mount with the flag gone — the panel offers the
  // button and nothing else.
  searchParams = new URLSearchParams();
  mockApiFetch.mockResolvedValue(payment());

  wrap(panel());

  expect(await screen.findByRole("link", { name: "payNow" })).toBeInTheDocument();
  expect(openAcquirerMock).not.toHaveBeenCalled();
});

it("does not re-open the acquirer if the tab reloads with the flag still in the URL", async () => {
  searchParams = new URLSearchParams(`${AUTO_OPEN_PARAM}=1`);
  mockApiFetch.mockResolvedValue(payment());

  const first = wrap(panel());
  await waitFor(() => {
    expect(openAcquirerMock).toHaveBeenCalledTimes(1);
  });
  first.unmount();

  // Same tab, same order, flag never stripped (the tab was evicted before the
  // URL rewrite landed) — the session-scoped one-shot still holds.
  wrap(panel());
  await waitFor(() => {
    expect(screen.getByRole("link", { name: "payNow" })).toBeInTheDocument();
  });
  expect(openAcquirerMock).toHaveBeenCalledTimes(1);
});

it("never auto-opens a payment with no acquirer page (wallet / settled)", async () => {
  searchParams = new URLSearchParams(`${AUTO_OPEN_PARAM}=1`);
  mockApiFetch.mockResolvedValue(payment({ provider: "wallet", intent_url: null }));

  wrap(panel());

  await waitFor(() => {
    expect(mockApiFetch).toHaveBeenCalled();
  });
  expect(openAcquirerMock).not.toHaveBeenCalled();
  expect(screen.queryByRole("link", { name: "payNow" })).not.toBeInTheDocument();
});

it("drops the button the moment the order stops awaiting payment", async () => {
  // The cached payment does not disappear when the query is disabled, so the
  // order's own status has to be part of the answer — otherwise a buyer who
  // pays and comes back is offered a button that would charge them twice.
  mockApiFetch.mockResolvedValue(payment());
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  const { rerender } = render(<QueryClientProvider client={qc}>{panel()}</QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "payNow" })).toBeInTheDocument();

  // The poll lands: webhook settled it, the order is `paid`.
  rerender(
    <QueryClientProvider client={qc}>{panel({ awaitingPayment: false })}</QueryClientProvider>,
  );
  expect(screen.queryByRole("link", { name: "payNow" })).not.toBeInTheDocument();
});

it("keeps a guest's access: the email rides the query string and the Guest token the header", async () => {
  mockApiFetch.mockResolvedValue(payment());

  wrap(
    panel({
      email: "guest@example.com",
      auth: {
        anonymous: true,
        headers: { Authorization: "Guest tok", "X-Guest-Email": "guest@example.com" },
      },
    }),
  );

  await screen.findByRole("link", { name: "payNow" });
  // `_resolve_actor` rebuilds the guest-token hash from the `email` param —
  // without it the API refuses the whole request.
  expect(mockApiFetch).toHaveBeenCalledWith(
    "/payments/by-order/order-1?email=guest%40example.com",
    {
      anonymous: true,
      headers: { Authorization: "Guest tok", "X-Guest-Email": "guest@example.com" },
    },
  );
});
