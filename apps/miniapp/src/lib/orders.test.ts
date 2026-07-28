import { describe, expect, it } from "vitest";

import { orderRefetchInterval } from "./orders";

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
