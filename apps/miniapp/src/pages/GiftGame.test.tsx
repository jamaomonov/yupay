import { describe, expect, test } from "vitest";

import { splitZones, zoneAfterPackageChange } from "./GiftGame";

import type { GiftPackage } from "@/lib/gifts";

function makePackage(prices: { zone: string; price_usd: string }[]): GiftPackage {
  return {
    id: 1,
    name: "Edition",
    image: null,
    discount_percent: null,
    prices: prices.map((p) => ({ zone: p.zone, price_usd: p.price_usd, price_uzs: null })),
  };
}

// Mirrors `GiftPurchasePanel.tsx::selectPackage` on the web storefront: a
// package/edition switch keeps the current region when possible, otherwise
// falls back to the app's default zone, then to whatever price the package
// does offer, and leaves the zone untouched only when the package has no
// prices at all (nothing sensible to fall back to).
describe("zoneAfterPackageChange", () => {
  test("keeps the current zone when the new package still prices it", () => {
    const pkg = makePackage([
      { zone: "CIS", price_usd: "1" },
      { zone: "RU", price_usd: "2" },
    ]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("RU");
  });

  test("falls back to the app's default zone when the current one isn't priced", () => {
    const pkg = makePackage([
      { zone: "CIS", price_usd: "1" },
      { zone: "KZ", price_usd: "3" },
    ]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("CIS");
  });

  test("falls back to the package's first price when neither current nor default is priced", () => {
    const pkg = makePackage([{ zone: "UA", price_usd: "4" }]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("UA");
  });

  test("leaves the zone unchanged when the package has no prices at all", () => {
    const pkg = makePackage([]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("RU");
  });
});

describe("splitZones", () => {
  test("splits at the visible count", () => {
    expect(splitZones(["CIS", "RU", "KZ", "UA", "TR"], 4)).toEqual({
      visible: ["CIS", "RU", "KZ", "UA"],
      overflow: ["TR"],
    });
  });

  test("empty overflow when everything fits", () => {
    expect(splitZones(["CIS", "RU"], 4)).toEqual({ visible: ["CIS", "RU"], overflow: [] });
  });

  test("handles an empty zone list", () => {
    expect(splitZones([], 4)).toEqual({ visible: [], overflow: [] });
  });
});
