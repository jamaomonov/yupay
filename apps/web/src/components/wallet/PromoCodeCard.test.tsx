// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PromoCodeCard } from "./PromoCodeCard";

import { formatUzs } from "@/lib/seo";
import { formatLedgerAmount } from "@/lib/wallet";
import { useToast } from "@/store/useToast";

/**
 * Promo redemption on the web wallet — the Mini App's `PromoCodeCard` ported
 * to this surface. Two properties matter most: every refusal reads as its
 * own sentence (a customer whose code merely expired must not think the
 * site is broken), and a fresh Idempotency-Key rides every attempt — never
 * one reused across presses, which is right for a top-up retry but wrong
 * here, where a second press means the customer typed a different code.
 *
 * Keys are rendered verbatim by the `next-intl` mock, so an assertion on
 * `promoExpired` is an assertion that the right branch ran.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

beforeEach(() => {
  useToast.setState({ toasts: [] });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

interface FakeResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

type FetchMock = ReturnType<
  typeof vi.fn<(url: string, init?: RequestInit) => Promise<FakeResponse>>
>;

function stubRedeem(body: unknown, ok: boolean, status: number): FetchMock {
  const fetchMock: FetchMock = vi.fn(() =>
    Promise.resolve({
      ok,
      status,
      json: () => Promise.resolve(body),
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderCard(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PromoCodeCard locale="ru" />
    </QueryClientProvider>,
  );
}

function apply(code: string): void {
  fireEvent.change(screen.getByLabelText("promoTitle"), { target: { value: code } });
  fireEvent.click(screen.getByRole("button", { name: "promoApply" }));
}

it("credits the balance and toasts the formatted amount", async () => {
  stubRedeem({ code: "WELCOME10", amount: "50000", currency: "UZS" }, true, 200);

  renderCard();
  apply("welcome10");

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  const [pushed] = useToast.getState().toasts;
  expect(pushed?.tone).toBe("success");
  // Was a raw `${amount} ${currency}` concatenation in the Mini App before
  // it switched to the page's own formatter — the same fix, here.
  expect(pushed?.message).toBe(
    `promoSuccess:${JSON.stringify({ amount: formatUzs("ru", 50000) })}`,
  );
  // The field clears — nothing left over to resubmit.
  expect(screen.getByLabelText("promoTitle")).toHaveValue("");
});

it.each([
  ["already_redeemed", "promoAlreadyUsed"],
  ["expired", "promoExpired"],
  ["exhausted", "promoExhausted"],
  ["inactive", "promoInactive"],
])("explains the %s refusal in its own words", async (code, key) => {
  stubRedeem({ detail: "conflict", code }, false, 409);

  renderCard();
  apply("USED10");

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  expect(useToast.getState().toasts[0]).toMatchObject({ message: key, tone: "error" });
});

it("falls back to the blanket wording for a 409 code it doesn't recognise", async () => {
  // A reason the server learned before this card did must read as "already
  // used or unavailable", not as an empty toast.
  stubRedeem({ detail: "conflict", code: "some_future_reason" }, false, 409);

  renderCard();
  apply("MYSTERY");

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  expect(useToast.getState().toasts[0]).toMatchObject({ message: "promoUsed", tone: "error" });
});

it("tells the customer the code doesn't exist, on a 404", async () => {
  stubRedeem({ detail: "promo code not found" }, false, 404);

  renderCard();
  apply("NOPE");

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  expect(useToast.getState().toasts[0]).toMatchObject({ message: "promoNotFound", tone: "error" });
});

it("does not submit an empty or whitespace-only code", () => {
  const fetchMock = stubRedeem({}, true, 200);
  renderCard();

  expect(screen.getByRole("button", { name: "promoApply" })).toBeDisabled();

  fireEvent.change(screen.getByLabelText("promoTitle"), { target: { value: "   " } });
  expect(screen.getByRole("button", { name: "promoApply" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "promoApply" }));

  expect(fetchMock).not.toHaveBeenCalled();
});

it("disables the button while the first attempt is in flight, so a second press fires nothing", async () => {
  const fetchMock = vi.fn(() => new Promise(() => void 0 /* never resolves */));
  vi.stubGlobal("fetch", fetchMock);

  renderCard();
  apply("SLOW10");

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "promoApply" })).toBeDisabled();
  });
  // A click on a disabled button never reaches the handler — this is the
  // guard against a double-submit while the request is still pending.
  fireEvent.click(screen.getByRole("button", { name: "promoApply" }));
  fireEvent.click(screen.getByRole("button", { name: "promoApply" }));

  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("mints a fresh Idempotency-Key for every attempt, never a reused one", async () => {
  const fetchMock = stubRedeem({ detail: "conflict", code: "expired" }, false, 409);

  renderCard();
  apply("FIRST10");
  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  useToast.setState({ toasts: [] });

  apply("SECOND10");
  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });

  expect(fetchMock).toHaveBeenCalledTimes(2);
  const headerOf = (call: number): string | null =>
    new Headers(fetchMock.mock.calls[call]?.[1]?.headers).get("Idempotency-Key");
  const key1 = headerOf(0);
  const key2 = headerOf(1);
  expect(key1).toBeTruthy();
  expect(key2).toBeTruthy();
  expect(key1).not.toBe(key2);
});

it("labels a non-UZS credit in its own currency, not in soum", async () => {
  // The wallet is UZS-only in practice, so `formatUzs` and
  // `formatLedgerAmount` agree on every credit issued today — which is
  // exactly why this needs a test rather than an eyeball. Nothing in
  // `PromoCreateIn` stops an admin issuing a promo in another currency, and
  // the response carries its own. A credit labelled in the wrong one is a
  // money-display bug only the customer would ever notice.
  stubRedeem({ code: "USDGIFT", amount: "12.50", currency: "USD" }, true, 200);

  renderCard();
  apply("usdgift");

  await waitFor(() => {
    expect(useToast.getState().toasts).toHaveLength(1);
  });
  expect(useToast.getState().toasts[0]?.message).toBe(
    `promoSuccess:${JSON.stringify({ amount: formatLedgerAmount("ru", 12.5, "USD") })}`,
  );
});
