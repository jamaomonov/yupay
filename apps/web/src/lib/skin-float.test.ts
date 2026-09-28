import { describe, expect, it } from "vitest";

import { floatPosition, wearBand } from "./skin-float";

describe("wearBand", () => {
  it.each([
    [0.0, "FN"],
    [0.069, "FN"],
    [0.07, "MW"],
    [0.149, "MW"],
    [0.15, "FT"],
    [0.379, "FT"],
    [0.38, "WW"],
    [0.449, "WW"],
    [0.45, "BS"],
    [1, "BS"],
  ])("%s -> %s", (v, band) => {
    expect(wearBand(v)).toBe(band);
  });
});

describe("floatPosition", () => {
  it("clamps to 0..100", () => {
    expect(floatPosition(-1)).toBe(0);
    expect(floatPosition(0.5)).toBe(50);
    expect(floatPosition(2)).toBe(100);
  });
});
