import { describe, expect, test } from "vitest";

import { reconcileSelection, splitZones, zoneAfterPackageChange } from "./GiftGame";

import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";

function makePackage(id: number, prices: { zone: string; price_usd: string }[]): GiftPackage {
  return {
    id,
    name: `Edition ${String(id)}`,
    image: null,
    discount_percent: null,
    prices: prices.map((p) => ({ zone: p.zone, price_usd: p.price_usd, price_uzs: null })),
  };
}

function makeDetail(packages: GiftPackage[], zoneDefault: string): GiftAppDetail {
  return {
    app_id: 1,
    name: "Game",
    image: null,
    type: "game",
    price_usd: null,
    price_uzs: null,
    discount_percent: null,
    packages_count: packages.length,
    dlc_count: 0,
    description: null,
    packages,
    dlc_total: 0,
    zones: [zoneDefault],
    zone_default: zoneDefault,
  };
}

// Mirrors `GiftPurchasePanel.tsx::selectPackage` on the web storefront: a
// package/edition switch keeps the current region when possible, otherwise
// falls back to the app's default zone, then to whatever price the package
// does offer, and leaves the zone untouched only when the package has no
// prices at all (nothing sensible to fall back to).
describe("zoneAfterPackageChange", () => {
  test("keeps the current zone when the new package still prices it", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "RU", price_usd: "2" },
    ]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("RU");
  });

  test("falls back to the app's default zone when the current one isn't priced", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "KZ", price_usd: "3" },
    ]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("CIS");
  });

  test("falls back to the package's first price when neither current nor default is priced", () => {
    const pkg = makePackage(1, [{ zone: "UA", price_usd: "4" }]);
    expect(zoneAfterPackageChange(pkg, "RU", "CIS")).toBe("UA");
  });

  test("leaves the zone unchanged when the package has no prices at all", () => {
    const pkg = makePackage(1, []);
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

// Guards the price-drift reload path in `GiftGame.tsx::handleBuy`: on a 422
// price-drift refresh, `load(true)` must reapply what the buyer had picked
// instead of resetting to `packages[0]`/`zone_default` like a fresh load.
describe("reconcileSelection", () => {
  test("keeps the previously selected package and zone when both still exist", () => {
    const detail = makeDetail(
      [
        makePackage(1, [{ zone: "CIS", price_usd: "1" }]),
        makePackage(2, [
          { zone: "CIS", price_usd: "2" },
          { zone: "RU", price_usd: "3" },
        ]),
      ],
      "CIS",
    );
    expect(reconcileSelection(detail, 2, "RU")).toEqual({ packageId: 2, zone: "RU" });
  });

  test("falls back to the first package when the previous one was dropped", () => {
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], "CIS");
    expect(reconcileSelection(detail, 99, "CIS")).toEqual({ packageId: 1, zone: "CIS" });
  });

  test("re-resolves the zone via zoneAfterPackageChange when the kept package no longer prices it", () => {
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], "CIS");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: 1, zone: "CIS" });
  });

  test("falls back to the app's default zone when there was no previous zone", () => {
    const detail = makeDetail(
      [
        makePackage(1, [
          { zone: "CIS", price_usd: "1" },
          { zone: "RU", price_usd: "2" },
        ]),
      ],
      "CIS",
    );
    expect(reconcileSelection(detail, 1, null)).toEqual({ packageId: 1, zone: "CIS" });
  });

  test("returns a null package and keeps the previous zone when the detail has no packages", () => {
    const detail = makeDetail([], "CIS");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: null, zone: "RU" });
  });
});
