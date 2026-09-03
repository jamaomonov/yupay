import { describe, expect, test } from "vitest";

import {
  countryAfterPackageChange,
  reconcileSelection,
  splitCountries,
  walletPayState,
} from "./GiftGame";

import type { GiftAppDetail, GiftPackage, GiftRegion } from "@/lib/gifts";

function makePackage(id: number, prices: { zone: string; price_usd: string }[]): GiftPackage {
  return {
    id,
    name: `Edition ${String(id)}`,
    image: null,
    discount_percent: null,
    prices: prices.map((p) => ({ zone: p.zone, price_usd: p.price_usd, price_uzs: null })),
  };
}

/** One country per zone, country code === zone label for readability — the
 *  logic under test only cares about the country <-> zone mapping shape,
 *  not real ISO codes (those are `./regions.test.ts`'s job). */
function makeRegions(pairs: [country: string, zone: string][]): GiftRegion[] {
  return pairs.map(([country, zone]) => ({ country, zone, price_usd: "0", price_uzs: null }));
}

function makeDetail(
  packages: GiftPackage[],
  regions: GiftRegion[],
  regionDefault: string,
): GiftAppDetail {
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
    regions,
    region_default: regionDefault,
  };
}

// Mirrors `GiftPurchasePanel.tsx::selectPackage` on the web storefront: a
// package/edition switch keeps the current country when its zone is still
// priced, otherwise falls back to the app's default country, then to
// whatever country covers the package's first price, and leaves the country
// untouched only when the package has no prices at all (nothing sensible to
// fall back to) — or the fallback zone maps to no known country.
describe("countryAfterPackageChange", () => {
  const regions = makeRegions([
    ["UZ", "CIS"],
    ["RU", "RU"],
    ["KZ", "KZ"],
    ["UA", "UA"],
  ]);

  test("keeps the current country when the new package still prices its zone", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "RU", price_usd: "2" },
    ]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });

  test("falls back to the app's default country when the current one isn't priced", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "KZ", price_usd: "3" },
    ]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("UZ");
  });

  test("falls back to a country covering the package's first price when neither current nor default is priced", () => {
    const pkg = makePackage(1, [{ zone: "UA", price_usd: "4" }]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("UA");
  });

  test("leaves the country unchanged when the package has no prices at all", () => {
    const pkg = makePackage(1, []);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });

  test("leaves the country unchanged when the fallback zone maps to no known country", () => {
    const pkg = makePackage(1, [{ zone: "MENA", price_usd: "9" }]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });
});

describe("splitCountries", () => {
  test("splits at the visible count", () => {
    expect(splitCountries(["UZ", "RU", "KZ", "UA", "TJ"], 4)).toEqual({
      visible: ["UZ", "RU", "KZ", "UA"],
      overflow: ["TJ"],
    });
  });

  test("empty overflow when everything fits", () => {
    expect(splitCountries(["UZ", "RU"], 4)).toEqual({ visible: ["UZ", "RU"], overflow: [] });
  });

  test("handles an empty country list", () => {
    expect(splitCountries([], 4)).toEqual({ visible: [], overflow: [] });
  });
});

// Guards the price-drift reload path in `GiftGame.tsx::handleBuy`: on a 422
// price-drift refresh, `load(true)` must reapply what the buyer had picked
// instead of resetting to `packages[0]`/`region_default` like a fresh load.
describe("reconcileSelection", () => {
  test("keeps the previously selected package and country when both still exist", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail(
      [
        makePackage(1, [{ zone: "CIS", price_usd: "1" }]),
        makePackage(2, [
          { zone: "CIS", price_usd: "2" },
          { zone: "RU", price_usd: "3" },
        ]),
      ],
      regions,
      "UZ",
    );
    expect(reconcileSelection(detail, 2, "RU")).toEqual({ packageId: 2, country: "RU" });
  });

  test("falls back to the first package when the previous one was dropped", () => {
    const regions = makeRegions([["UZ", "CIS"]]);
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], regions, "UZ");
    expect(reconcileSelection(detail, 99, "UZ")).toEqual({ packageId: 1, country: "UZ" });
  });

  test("re-resolves the country via countryAfterPackageChange when the kept package no longer prices it", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], regions, "UZ");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: 1, country: "UZ" });
  });

  test("falls back to the app's default country when there was no previous country", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail(
      [
        makePackage(1, [
          { zone: "CIS", price_usd: "1" },
          { zone: "RU", price_usd: "2" },
        ]),
      ],
      regions,
      "UZ",
    );
    expect(reconcileSelection(detail, 1, null)).toEqual({ packageId: 1, country: "UZ" });
  });

  test("returns a null package and keeps the previous country when the detail has no packages", () => {
    const regions = makeRegions([["UZ", "CIS"]]);
    const detail = makeDetail([], regions, "UZ");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: null, country: "RU" });
  });

  test("never throws when the detail predates the country picker entirely (version-skewed API)", () => {
    // Same version-skew case as `gifts.test.ts::priceFor` — a detail with
    // `regions`/`region_default` absent outright must degrade, not throw;
    // `GiftGame`'s own `countries.length === 0` guard is what actually
    // keeps this off screen in practice, but the pure function must still
    // be safe to call directly.
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], [], "UZ");
    const { regions: _regions, region_default: _regionDefault, ...withoutRegions } = detail;
    expect(() => reconcileSelection(withoutRegions, 1, null)).not.toThrow();
  });
});

// Wallet ("pay from balance") affordability decision — mirrors `TopUp.tsx`'s
// inline `walletEnough`/`walletShortfall`/`disabled` math (see
// `WalletPayOption.tsx`), extracted here as a pure function so it's
// testable under this app's node-env convention (no RTL, no rendering).
// `total` is the selected region's `price_uzs` — `null` only when FX is
// unavailable, which must degrade to a non-selectable "unknown total"
// state rather than comparing against a guessed number.
describe("walletPayState", () => {
  test("is optimistically enough while the balance is still loading", () => {
    expect(
      walletPayState({ balance: null, total: 100_000, loading: true, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is enough when the balance covers the total exactly", () => {
    expect(
      walletPayState({ balance: 100_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is enough when the balance exceeds the total", () => {
    expect(
      walletPayState({ balance: 150_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is short and disabled when the balance doesn't cover the total", () => {
    expect(
      walletPayState({ balance: 40_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 60_000, unknownTotal: false });
  });

  test("maintenance disables the tile even when the balance is enough", () => {
    expect(
      walletPayState({
        balance: 150_000,
        total: 100_000,
        loading: false,
        visibility: "maintenance",
      }),
    ).toEqual({ enough: true, disabled: true, shortfall: 0, unknownTotal: false });
  });

  test("a null total (FX-unavailable price_uzs) is a disabled unknown state, never a guessed shortfall", () => {
    expect(
      walletPayState({ balance: 150_000, total: null, loading: false, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 0, unknownTotal: true });
  });

  test("a null total overrides the loading optimism — there's nothing to be optimistic about", () => {
    expect(
      walletPayState({ balance: null, total: null, loading: true, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 0, unknownTotal: true });
  });
});
