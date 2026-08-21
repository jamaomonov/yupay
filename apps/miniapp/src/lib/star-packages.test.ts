import { describe, expect, test } from "vitest";

import { packagePrice, STAR_PACKAGES, visibleStarPackages } from "./star-packages";

describe("visibleStarPackages", () => {
  test("hides packs outside admin bounds", () => {
    expect(visibleStarPackages(100, 1000)).toEqual([100, 150, 250, 350, 500, 750, 1000]);
  });

  test("includes every pack when the bounds cover the whole list", () => {
    expect(visibleStarPackages(50, 2500)).toEqual([...STAR_PACKAGES]);
  });

  test("is empty when no pack falls in range", () => {
    expect(visibleStarPackages(3000, 4000)).toEqual([]);
  });

  test("keeps the endpoints — a closed interval like the server's check", () => {
    expect(visibleStarPackages(75, 500)).toEqual([75, 100, 150, 250, 350, 500]);
  });
});

describe("packagePrice", () => {
  test("prices a pack as N times the per-star display price", () => {
    expect(packagePrice(500, 250)).toBe(125000);
  });

  test("scales linearly — no volume-discount bands for a unit SKU", () => {
    expect(packagePrice(100, 250)).toBe(25000);
    expect(packagePrice(1000, 250)).toBe(250000);
  });
});
