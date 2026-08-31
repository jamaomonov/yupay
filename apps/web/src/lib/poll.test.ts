import { describe, expect, test } from "vitest";

import { orderPollInterval, pollInterval } from "./poll";

describe("pollInterval", () => {
  test("is long enough that a waiting crowd is not the load", () => {
    // The fallback switches on when the socket drops, which is when the API is
    // already struggling. At the previous flat 4s a hundred waiting customers
    // were ~25 req/s on the order query alone.
    expect(pollInterval()).toBeGreaterThanOrEqual(8_000);
  });

  test("widens on consecutive failures", () => {
    expect(pollInterval(3)).toBeGreaterThan(pollInterval(0) / 2 + 8_000);
  });

  test("stays capped, so a recovered API is noticed within a minute", () => {
    for (const failures of [4, 10, 50, 1000]) {
      expect(pollInterval(failures)).toBeLessThanOrEqual(60_000);
    }
  });

  test("two clients that dropped together do not retry together", () => {
    const samples = new Set(Array.from({ length: 40 }, () => pollInterval()));
    expect(samples.size).toBeGreaterThan(1);
  });

  test("jitter stays inside a sane band", () => {
    const values = Array.from({ length: 200 }, () => pollInterval());
    expect(Math.min(...values)).toBeGreaterThanOrEqual(8_000);
    expect(Math.max(...values)).toBeLessThanOrEqual(16_000);
  });
});

describe("orderPollInterval", () => {
  test("never polls a terminal or unknown status", () => {
    for (const status of [undefined, "delivered", "cancelled", "refunded", "expired"]) {
      expect(orderPollInterval(status, { connected: false })).toBe(false);
      expect(orderPollInterval(status, { connected: true })).toBe(false);
    }
  });

  test("a connected socket silences polling only for pending_payment", () => {
    expect(orderPollInterval("pending_payment", { connected: true })).toBe(false);
    const ms = orderPollInterval("pending_payment", { connected: false });
    expect(typeof ms).toBe("number");
  });

  test("keeps polling the delivery window even while the socket says connected", () => {
    // A zombie socket still reports connected; the delivered push dies in it.
    // The socket is an accelerator, the poll is the reconciler.
    for (const status of ["paid", "fulfilling", "fulfilled"]) {
      const ms = orderPollInterval(status, { connected: true });
      expect(typeof ms).toBe("number");
      expect(ms as number).toBeGreaterThan(0);
    }
  });

  test("widens with consecutive failures like the bare interval", () => {
    const later = orderPollInterval("fulfilling", { connected: false, failures: 3 });
    expect(later as number).toBeGreaterThan(8_000);
  });
});
