import { describe, expect, test } from "vitest";

import {
  MAX_STAR_LAYERS,
  packagePrice,
  STAR_PACKAGES,
  starLayers,
  visibleStarPackages,
} from "./star-packages";

describe("visibleStarPackages", () => {
  test("hides packs outside admin bounds", () => {
    expect(visibleStarPackages(100, 1000)).toEqual([100, 150, 250, 350, 500, 750, 1000]);
  });

  test("includes every pack when the bounds cover the whole list", () => {
    // Derived from the list, not a literal: the old `2500` was the largest
    // pack at the time, so adding a bigger one broke a test whose point has
    // nothing to do with which packs exist.
    const widest = Math.max(...STAR_PACKAGES);
    expect(visibleStarPackages(Math.min(...STAR_PACKAGES), widest)).toEqual([...STAR_PACKAGES]);
  });

  test("offers the 5000 pack at the SKU's configured ceiling", () => {
    // `tg-stars-any` on prod is min_qty 50 / max_qty 5000. A pack the admin
    // has raised the ceiling for but the storefront never draws is invisible
    // to the customer, which is the only way this list can be wrong.
    expect(visibleStarPackages(50, 5000)).toContain(5000);
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

describe("starLayers", () => {
  test("grows the pile with the pack's magnitude", () => {
    expect(starLayers(50)).toBe(1);
    expect(starLayers(100)).toBe(2);
    expect(starLayers(500)).toBe(3);
    expect(starLayers(5000)).toBe(4);
  });

  test("never draws more than the stack allows", () => {
    // The offsets are tuned for MAX_STAR_LAYERS; a fifth copy would sit
    // outside the 48px box rather than behind the others.
    for (const n of STAR_PACKAGES) {
      expect(starLayers(n)).toBeGreaterThanOrEqual(1);
      expect(starLayers(n)).toBeLessThanOrEqual(MAX_STAR_LAYERS);
    }
  });

  test("uses every pile, so neighbouring tiles usually differ", () => {
    // Thresholds that bunch most packs onto one step make the art say nothing
    // again, which is the thing this replaced.
    expect(new Set(STAR_PACKAGES.map(starLayers)).size).toBe(MAX_STAR_LAYERS);
  });

  test("is monotonic — a bigger pack never shows a smaller pile", () => {
    // The whole point is that the art reads as size; a dip anywhere would say
    // the opposite of the number beside it.
    const piles = STAR_PACKAGES.map(starLayers);
    expect([...piles].sort((a, b) => a - b)).toEqual(piles);
  });
});
