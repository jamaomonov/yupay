import { describe, expect, it } from "vitest";

import {
  addPack,
  CART_MAX_UNITS,
  cartUnits,
  expandPieces,
  splitRounded,
  stepPack,
} from "./pack-cart";

describe("pack cart", () => {
  it("adds a pack once and keeps the rest of the order", () => {
    const a = addPack({}, "p110", true);
    const b = addPack(a, "p341", true);
    expect(b).toEqual({ p110: 1, p341: 1 });
    expect(addPack(b, "p110", true)).toBe(b);
  });

  it("starts over for a pack of another product", () => {
    expect(addPack({ p110: 3 }, "voucher", false)).toEqual({ voucher: 1 });
  });

  it("steps counts and drops a pack at zero", () => {
    expect(stepPack({ p110: 1 }, "p110", 1)).toEqual({ p110: 2 });
    expect(stepPack({ p110: 1, p341: 1 }, "p110", -1)).toEqual({ p341: 1 });
  });

  it("stops at the API's line limit", () => {
    const full = { p110: CART_MAX_UNITS };
    expect(stepPack(full, "p110", 1)).toBe(full);
    expect(addPack(full, "p341", true)).toBe(full);
    expect(cartUnits(stepPack(full, "p110", -1))).toBe(CART_MAX_UNITS - 1);
  });

  it("expands every piece into its own line", () => {
    const lines = expandPieces(
      [
        { skuId: "p110", count: 3 },
        { skuId: "p341", count: 1 },
      ],
      (sku_id) => ({ sku_id, qty: 1 }),
    );
    expect(lines.map((l) => l.sku_id)).toEqual(["p110", "p110", "p110", "p341"]);
  });

  it("rounds lines so they add up to the rounded total", () => {
    // Rounded one by one the lines add up to 70 771 under a 70 772 total.
    const { lines, total } = splitRounded([35266.2, 35505.4]);
    expect(total).toBe(70772);
    expect(lines).toEqual([35266, 35506]); // the 0.4 lost more than the 0.2
    expect(splitRounded([35265.7, 35505.1]).lines).toEqual([35266, 35505]); // plain rounding
    const cents = splitRounded([0.335, 0.335, 0.335], 0.01);
    expect(Math.round(cents.lines.reduce((n, x) => n + x, 0) * 100)).toBe(
      Math.round(cents.total * 100),
    );
  });
});
