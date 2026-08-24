import { describe, expect, test } from "vitest";

import { packagePrice, STAR_PACKAGES, visibleStarPackages } from "./star-packages";

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
