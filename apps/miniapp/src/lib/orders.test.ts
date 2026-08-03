import { describe, expect, it } from "vitest";

import {
  methodVisibility,
  orderRefetchInterval,
  providerStatusMap,
  selectActiveMethodId,
  type ProviderStatus,
} from "./orders";

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
