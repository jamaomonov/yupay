import { describe, expect, it } from "vitest";

import { createGate, mapLimit } from "./map-limit";

describe("mapLimit", () => {
  it("keeps order and never runs more than the limit at once", async () => {
    let running = 0;
    let peak = 0;
    const out = await mapLimit([5, 1, 4, 2, 3], 2, async (n) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((r) => setTimeout(r, n));
      running -= 1;
      return n * 10;
    });
    expect(out).toEqual([50, 10, 40, 20, 30]);
    expect(peak).toBe(2);
  });

  it("handles an empty list", async () => {
    expect(await mapLimit([], 3, (n: number) => Promise.resolve(n))).toEqual([]);
  });
});

describe("createGate", () => {
  it("caps calls across callers and runs them all", async () => {
    const gate = createGate(2);
    let running = 0;
    let peak = 0;
    const job = (n: number) =>
      gate(async () => {
        running += 1;
        peak = Math.max(peak, running);
        await new Promise((r) => setTimeout(r, n));
        running -= 1;
        return n;
      });
    const pageA = Promise.all([job(5), job(1), job(4)]);
    const pageB = Promise.all([job(2), job(3)]);
    expect(await pageA).toEqual([5, 1, 4]);
    expect(await pageB).toEqual([2, 3]);
    expect(peak).toBe(2);
  });

  it("frees the slot when a call fails", async () => {
    const gate = createGate(1);
    await expect(gate(() => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
    expect(await gate(() => Promise.resolve(7))).toBe(7);
  });
});
