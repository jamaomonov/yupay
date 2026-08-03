import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import {
  methodVisibility,
  orderRefetchInterval,
  performCheckout,
  providerStatusMap,
  requiresAcquirerAvailabilityCheck,
  selectActiveMethodId,
  type OrderOut,
  type PaymentOut,
  type ProviderStatus,
} from "./orders";

import type * as ApiModule from "./api";

// `performCheckout` (the body of `useCheckout`'s mutation, extracted so it's
// testable without mounting a React hook — this suite runs under
// `environment: "node"`, no DOM/React Testing Library) calls `apiGet`/
// `apiPost` directly. Mock only those two; keep every other export (notably
// `ApiError`, which `performCheckout` throws) real via `importOriginal`.
const mockApiGet = vi.fn<(path: string) => Promise<unknown>>();
const mockApiPost =
  vi.fn<(path: string, body: unknown, opts?: Record<string, unknown>) => Promise<unknown>>();

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof ApiModule>();
  return {
    ...actual,
    apiGet: (path: string) => mockApiGet(path),
    apiPost: (path: string, body: unknown, opts?: Record<string, unknown>) =>
      mockApiPost(path, body, opts),
  };
});

describe("orderRefetchInterval", () => {
  it("returns false when the order has no status yet", () => {
    expect(orderRefetchInterval(undefined, { appActive: true, realtimeConnected: false })).toBe(
      false,
    );
  });

  it("returns false while the app is minimised, even mid-flight", () => {
    expect(orderRefetchInterval("paid", { appActive: false, realtimeConnected: false })).toBe(
      false,
    );
  });

  it("stops REST polling once the order-updates WebSocket is connected", () => {
    for (const status of ["pending_payment", "paid", "fulfilling", "fulfilled"] as const) {
      expect(orderRefetchInterval(status, { appActive: true, realtimeConnected: true })).toBe(
        false,
      );
    }
  });

  it("polls every 3s for in-motion statuses when there is no live socket", () => {
    for (const status of ["pending_payment", "paid", "fulfilling", "fulfilled"] as const) {
      expect(orderRefetchInterval(status, { appActive: true, realtimeConnected: false })).toBe(
        3_000,
      );
    }
  });

  it("never polls terminal statuses, socket or not", () => {
    for (const status of ["delivered", "cancelled", "expired", "refunded"] as const) {
      expect(orderRefetchInterval(status, { appActive: true, realtimeConnected: false })).toBe(
        false,
      );
      expect(orderRefetchInterval(status, { appActive: true, realtimeConnected: true })).toBe(
        false,
      );
    }
  });
});

describe("providerStatusMap + methodVisibility", () => {
  // One active, one under maintenance, one omitted entirely (admin-disabled).
  const providers: ProviderStatus[] = [
    { slug: "click_miniapp", status: "active" },
    { slug: "payme", status: "maintenance" },
  ];
  const bySlug = providerStatusMap(providers);

  it("keeps an active provider selectable", () => {
    expect(methodVisibility("click_miniapp", bySlug)).toBe("active");
  });

  it("flags a maintenance provider as non-clickable but still rendered", () => {
    expect(methodVisibility("payme", bySlug)).toBe("maintenance");
  });

  it("hides a provider slug absent from the response entirely", () => {
    expect(methodVisibility("uzum", bySlug)).toBe("hidden");
  });

  it("fails open (treats every method as active) before the fetch resolves", () => {
    expect(methodVisibility("click_miniapp", null)).toBe("active");
    expect(methodVisibility("uzum", null)).toBe("active");
  });
});

describe("selectActiveMethodId", () => {
  const methods = [
    { id: "click", provider: "click_miniapp" },
    { id: "payme", provider: "payme" },
    { id: "uzum", provider: "uzum" },
  ];

  it("keeps the current selection when its provider is active", () => {
    const bySlug = providerStatusMap([{ slug: "click_miniapp", status: "active" }]);
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("click");
  });

  it("reselects the first active method when the hardcoded default is under maintenance", () => {
    const bySlug = providerStatusMap([
      { slug: "click_miniapp", status: "maintenance" },
      { slug: "payme", status: "active" },
    ]);
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("payme");
  });

  it("reselects the first active method when the default is absent (admin-disabled)", () => {
    const bySlug = providerStatusMap([{ slug: "uzum", status: "active" }]);
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("uzum");
  });

  it("returns null when no method is active, so nothing stays submittable", () => {
    const bySlug = providerStatusMap([
      { slug: "click_miniapp", status: "maintenance" },
      { slug: "payme", status: "maintenance" },
    ]);
    expect(selectActiveMethodId(methods, "click", bySlug)).toBeNull();
  });
});

describe("requiresAcquirerAvailabilityCheck", () => {
  it("exempts the in-house providers — wallet (pay-from-balance) and mock", () => {
    expect(requiresAcquirerAvailabilityCheck("wallet")).toBe(false);
    expect(requiresAcquirerAvailabilityCheck("mock")).toBe(false);
  });

  it("still enforces the check for every managed acquirer slug", () => {
    for (const slug of ["click_miniapp", "payme", "uzum", "octo", "crypto"]) {
      expect(requiresAcquirerAvailabilityCheck(slug)).toBe(true);
    }
  });
});

describe("performCheckout", () => {
  const ORDER: OrderOut = {
    id: "order-1",
    status: "pending_payment",
    currency: "USD",
    total_usd: "10.00",
    total_charged: "10.00",
    payment_provider: null,
    fx_snapshot_id: null,
    expires_at: "2026-08-04T00:00:00Z",
    created_at: "2026-08-04T00:00:00Z",
    paid_at: null,
    fulfilled_at: null,
    delivered_at: null,
    cancelled_at: null,
    items: [],
  };
  const PAYMENT: PaymentOut = {
    id: "payment-1",
    order_id: "order-1",
    provider: "wallet",
    status: "succeeded",
    amount: "10.00",
    currency: "USD",
    intent_url: null,
    external_id: null,
  };

  let qc: QueryClient;

  beforeEach(() => {
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mockApiGet.mockReset();
    mockApiPost.mockReset();
    mockApiPost.mockImplementation((path) => {
      if (path === "/api/v1/orders") return Promise.resolve(ORDER);
      if (path === "/api/v1/payments/intents") return Promise.resolve(PAYMENT);
      return Promise.reject(new Error(`unexpected apiPost path: ${path}`));
    });
  });

  // Regression: GET /payments/providers now (Task 4) lists managed acquirer
  // slugs only and intentionally never returns "wallet" — the pay-from-
  // balance checkout used to read that absence as "unavailable" and throw a
  // 409 before ever creating an order, making the wallet payment method
  // completely unusable in the miniapp (TopUp.tsx → PROVIDER_BY_METHOD_FULL
  // → provider: "wallet").
  it("does not block the in-house wallet provider, even when /payments/providers omits it", async () => {
    mockApiGet.mockResolvedValue({
      providers: [{ slug: "click_miniapp", status: "active" }],
    });

    const result = await performCheckout(qc, {
      skuId: "sku-1",
      fulfillmentData: {},
      provider: "wallet",
    });

    expect(result).toEqual({ order: ORDER, payment: PAYMENT });
    expect(mockApiPost).toHaveBeenNthCalledWith(
      1,
      "/api/v1/orders",
      expect.objectContaining({ currency: "USD" }),
      expect.anything(),
    );
    expect(mockApiPost).toHaveBeenNthCalledWith(
      2,
      "/api/v1/payments/intents",
      { order_id: ORDER.id, provider: "wallet" },
      expect.anything(),
    );
  });

  // Don't fetch /payments/providers at all for an in-house provider — there's
  // nothing to look up there, and a needless round-trip only slows checkout.
  it("skips the /payments/providers round-trip entirely for the wallet provider", async () => {
    await performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "wallet" });

    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("still rejects a non-active acquirer with a 409 before creating an order", async () => {
    mockApiGet.mockResolvedValue({
      providers: [{ slug: "payme", status: "maintenance" }],
    });

    await expect(
      performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "payme" }),
    ).rejects.toThrow(ApiError);
    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it("still proceeds for an acquirer the providers list reports active", async () => {
    mockApiGet.mockResolvedValue({
      providers: [{ slug: "click_miniapp", status: "active" }],
    });

    const result = await performCheckout(qc, {
      skuId: "sku-1",
      fulfillmentData: {},
      provider: "click_miniapp",
    });

    expect(result).toEqual({ order: ORDER, payment: PAYMENT });
    expect(mockApiGet).toHaveBeenCalledWith("/api/v1/payments/providers");
  });
});
