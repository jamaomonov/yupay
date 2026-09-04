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

  it("lets a connected socket silence polling only for pending_payment", () => {
    // pending_payment can sit for hours and its exit is user-driven (the
    // resume refetch catches it), so the live socket makes polling redundant.
    expect(
      orderRefetchInterval("pending_payment", { appActive: true, realtimeConnected: true }),
    ).toBe(false);
  });

  it("keeps polling the delivery window even while the socket says connected", () => {
    // A suspended WebView leaves a zombie socket that still reports connected;
    // the delivered push dies in it and the screen freezes on "fulfilling".
    // The socket is an accelerator, the poll is the reconciler.
    for (const status of ["paid", "fulfilling", "fulfilled"] as const) {
      const ms = orderRefetchInterval(status, { appActive: true, realtimeConnected: true });
      expect(typeof ms).toBe("number");
      expect(ms as number).toBeGreaterThan(0);
    }
  });

  it("polls in-motion statuses when there is no live socket", () => {
    // The exact number moved from a flat 3s to a jittered 8s and up — see
    // POLL_BASE_MS and the backoff tests below. What this pins is which
    // statuses poll at all.
    for (const status of ["pending_payment", "paid", "fulfilling", "fulfilled"] as const) {
      const ms = orderRefetchInterval(status, { appActive: true, realtimeConnected: false });
      expect(typeof ms).toBe("number");
      expect(ms as number).toBeGreaterThan(0);
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
  it("exempts only mock — wallet is checked so maintenance can block it", () => {
    expect(requiresAcquirerAvailabilityCheck("mock")).toBe(false);
    expect(requiresAcquirerAvailabilityCheck("wallet")).toBe(true);
  });

  it("still enforces the check for every managed acquirer slug", () => {
    for (const slug of ["click_miniapp", "payme", "uzum", "octo", "crypto", "wallet"]) {
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
    discount_charged: "0",
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
    mockApiGet.mockResolvedValue({
      providers: [{ slug: "wallet", status: "active" }],
    });
    mockApiPost.mockReset();
    mockApiPost.mockImplementation((path) => {
      if (path === "/api/v1/orders") return Promise.resolve(ORDER);
      if (path === "/api/v1/payments/intents") return Promise.resolve(PAYMENT);
      return Promise.reject(new Error(`unexpected apiPost path: ${path}`));
    });
  });

  it("lets wallet checkout through when /payments/providers lists it as active", async () => {
    mockApiGet.mockResolvedValue({
      providers: [
        { slug: "click_miniapp", status: "active" },
        { slug: "wallet", status: "active" },
      ],
    });

    const result = await performCheckout(qc, {
      skuId: "sku-1",
      fulfillmentData: {},
      provider: "wallet",
    });

    expect(result).toEqual({ order: ORDER, payment: PAYMENT });
    expect(mockApiPost).toHaveBeenNthCalledWith(
      2,
      "/api/v1/payments/intents",
      { order_id: ORDER.id, provider: "wallet" },
      expect.anything(),
    );
  });

  it("blocks wallet checkout with a 409 when the list has it in maintenance", async () => {
    mockApiGet.mockResolvedValue({
      providers: [{ slug: "wallet", status: "maintenance" }],
    });

    await expect(
      performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "wallet" }),
    ).rejects.toMatchObject({ status: 409 });
    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it("skips the /payments/providers round-trip entirely for mock", async () => {
    await performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "mock" });

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

  // Task 8: a unit SKU (Telegram Stars) is bought as a real quantity, not the
  // usual single line + `amount_usd`.
  it("sends a unit SKU's tapped/typed count as qty, with no amount_usd", async () => {
    await performCheckout(qc, {
      skuId: "sku-stars-unit",
      fulfillmentData: { username: "durov" },
      qty: 500,
      provider: "wallet",
    });

    expect(mockApiPost).toHaveBeenNthCalledWith(
      1,
      "/api/v1/orders",
      expect.objectContaining({
        items: [
          {
            sku_id: "sku-stars-unit",
            qty: 500,
            fulfillment_data: { username: "durov" },
          },
        ],
      }),
      expect.anything(),
    );
  });

  it("defaults every other line to qty: 1 when qty is left unset", async () => {
    await performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "wallet" });

    expect(mockApiPost).toHaveBeenNthCalledWith(
      1,
      "/api/v1/orders",
      expect.objectContaining({
        items: [{ sku_id: "sku-1", qty: 1, fulfillment_data: {} }],
      }),
      expect.anything(),
    );
  });

  // Sticky order key (GiftGame.tsx): a caller keeps `Idempotency-Key` sticky
  // across a failed-payment retry so `create_order`'s replay-by-key
  // (`_existing_idempotent_order` in `orders/service.py`) resumes the same
  // order instead of minting a second one. `performCheckout` must forward a
  // caller-supplied key untouched; `TopUp`'s call site never passes one, so
  // omitting it must keep generating one internally, byte-identically to
  // before this field existed.
  it("forwards a caller-supplied order idempotency key verbatim, instead of generating one", async () => {
    await performCheckout(qc, {
      skuId: "sku-1",
      fulfillmentData: {},
      provider: "wallet",
      orderIdempotencyKey: "sticky-order-key-123",
    });

    expect(mockApiPost).toHaveBeenNthCalledWith(1, "/api/v1/orders", expect.anything(), {
      idempotencyKey: "sticky-order-key-123",
    });
  });

  it("still generates an order idempotency key when none is supplied", async () => {
    await performCheckout(qc, { skuId: "sku-1", fulfillmentData: {}, provider: "wallet" });

    const call = mockApiPost.mock.calls[0] as [string, unknown, { idempotencyKey?: string }];
    expect(call[0]).toBe("/api/v1/orders");
    expect(call[2]?.idempotencyKey).toMatch(/^order-/);
  });
});

describe("polling backs off instead of piling on", () => {
  const opts = { appActive: true, realtimeConnected: false };

  it("the interval is long enough that a crowd does not become the load", () => {
    // The socket drops exactly when the API is struggling, which is when this
    // fallback switches on. At 3s, a hundred customers waiting on an order
    // produced ~33 req/s of pure polling — plus the deliveries poll on top —
    // arriving precisely when there is no capacity for it. That is a positive
    // feedback loop, not a fallback.
    const interval = orderRefetchInterval("paid", opts);
    expect(typeof interval).toBe("number");
    expect(interval as number).toBeGreaterThanOrEqual(8_000);
  });

  it("consecutive failures widen the gap", () => {
    const first = orderRefetchInterval("paid", opts) as number;
    const later = orderRefetchInterval("paid", { ...opts, failures: 3 }) as number;
    expect(later).toBeGreaterThan(first);
  });

  it("the backoff is capped, so a recovered API is noticed", () => {
    const far = orderRefetchInterval("paid", { ...opts, failures: 50 }) as number;
    expect(far).toBeLessThanOrEqual(60_000);
  });

  it("two clients do not line up", () => {
    // Without jitter every client that dropped at the same moment retries at
    // the same moment, forever — the herd stays a herd.
    const samples = new Set(
      Array.from({ length: 40 }, () => orderRefetchInterval("paid", opts) as number),
    );
    expect(samples.size).toBeGreaterThan(1);
  });

  it("jitter stays within a sane band", () => {
    const values = Array.from({ length: 200 }, () => orderRefetchInterval("paid", opts) as number);
    expect(Math.min(...values)).toBeGreaterThanOrEqual(8_000);
    expect(Math.max(...values)).toBeLessThanOrEqual(16_000);
  });

  it("everything that stopped polling before still does", () => {
    expect(orderRefetchInterval("delivered", opts)).toBe(false);
    expect(orderRefetchInterval("paid", { ...opts, appActive: false })).toBe(false);
    // paid + connected socket now polls on purpose (zombie-socket reconciler);
    // the connected suppression that survives is pending_payment only.
    expect(orderRefetchInterval("pending_payment", { ...opts, realtimeConnected: true })).toBe(
      false,
    );
  });
});
