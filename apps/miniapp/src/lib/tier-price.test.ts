import { describe, expect, it } from "vitest";

import { tierPrice } from "./variable-amount";

import type { PricedPack } from "./variable-amount";

/**
 * The page must show what the server will charge. This mirrors
 * `orders.service.tier_price_usd`, so the two rule sets are asserted the same
 * way — including the cap, without which buying less costs more.
 */

// 20% on the small packs, ~10% on the biggest: the volume discount this exists for.
const PACKS: PricedPack[] = [
  { units: 50, price: 930 },
  { units: 100, price: 1850 },
  { units: 500, price: 8890 },
  { units: 2500, price: 42510 },
];

describe("tierPrice", () => {
  it.each(PACKS)("an exact pack amount costs exactly the pack ($units)", (pack) => {
    expect(tierPrice(pack.units, PACKS)).toBeCloseTo(pack.price, 6);
  });

  it("prices an in-between amount at its band's rate", () => {
    expect(tierPrice(74, PACKS)).toBeCloseTo(74 * (930 / 50), 6);
  });

  it("never charges more than the next pack up", () => {
    // 499 at the 100-pack's rate would be 9231.5 — more than the 500 pack.
    expect(tierPrice(499, PACKS)).toBe(8890);
  });

  it("never lets more units cost less in total", () => {
    const amounts = [50, 74, 100, 250, 481, 499, 500, 501, 1000, 2500, 5000];
    const totals = amounts.map((n) => tierPrice(n, PACKS) ?? 0);
    expect(totals).toEqual([...totals].sort((a, b) => a - b));
  });

  it("passes the volume discount through to the typed amount", () => {
    const small = (tierPrice(50, PACKS) ?? 0) / 50;
    const large = (tierPrice(2500, PACKS) ?? 0) / 2500;
    expect(large).toBeLessThan(small);
  });

  it("has no price below the smallest pack rather than guessing one", () => {
    expect(tierPrice(10, PACKS)).toBeNull();
  });

  it("has no price when there are no packs at all — the Steam wallet case", () => {
    expect(tierPrice(500, [])).toBeNull();
  });
});
