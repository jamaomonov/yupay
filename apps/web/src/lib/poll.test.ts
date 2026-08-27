import { describe, expect, test } from "vitest";

import { pollInterval } from "./poll";

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
