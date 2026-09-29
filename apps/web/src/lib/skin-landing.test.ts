import { describe, expect, it } from "vitest";

import { findWeapon, landingPaths, weaponSlug } from "./skin-landing";

const FACETS = {
  categories: [
    { value: "rifles", count: 4148 },
    { value: "knives", count: 3505 },
  ],
  weapons: [
    { value: "AK-47", count: 594 },
    { value: "M4A1-S", count: 405 },
    { value: "Desert Eagle", count: 381 },
    { value: "★ Karambit", count: 120 },
  ],
  exteriors: [],
  rarities: [],
};

describe("skin landings", () => {
  it("slugs a weapon the way people type it", () => {
    expect(weaponSlug("AK-47")).toBe("ak-47");
    expect(weaponSlug("M4A1-S")).toBe("m4a1-s");
    expect(weaponSlug("Desert Eagle")).toBe("desert-eagle");
    expect(weaponSlug("★ Karambit")).toBe("karambit");
  });

  it("finds the weapon behind a slug, or nothing", () => {
    expect(findWeapon(FACETS, "desert-eagle")).toEqual({ value: "Desert Eagle", count: 381 });
    expect(findWeapon(FACETS, "nope")).toBeNull();
  });

  it("lists every category and weapon page", () => {
    expect(landingPaths(FACETS)).toEqual([
      "/skins/category/rifles",
      "/skins/category/knives",
      "/skins/weapon/ak-47",
      "/skins/weapon/m4a1-s",
      "/skins/weapon/desert-eagle",
      "/skins/weapon/karambit",
    ]);
  });
});
