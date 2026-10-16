import { describe, expect, it } from "vitest";

import { translate } from "./i18n/core";
import {
  isUncheckedAccount,
  regionBrandSlug,
  regionLabel,
  resolveRegion,
  switcherRegions,
} from "./region";

const MLBB_REGIONS = [
  { code: "global", slug: "mobile-legends" },
  { code: "ru", slug: "mobile-legends-ru" },
  { code: "ph", slug: "mobile-legends-ph" },
];

describe("resolveRegion", () => {
  it("resolves a regional route slug to its main brand and preselects the region", () => {
    expect(
      resolveRegion("mobile-legends-ph", {
        region_code: "ph",
        region_of: "mobile-legends",
        regions: MLBB_REGIONS,
      }),
    ).toEqual({ base: "mobile-legends", region: "ph" });
  });

  it("keeps a main brand as its own base, region global", () => {
    expect(
      resolveRegion("mobile-legends", {
        region_code: "global",
        region_of: null,
        regions: MLBB_REGIONS,
      }),
    ).toEqual({ base: "mobile-legends", region: "global" });
  });

  it("defaults while the summary is unknown or from an older API", () => {
    expect(resolveRegion("pubg-mobile", undefined)).toEqual({
      base: "pubg-mobile",
      region: "global",
    });
    expect(resolveRegion("pubg-mobile", {})).toEqual({ base: "pubg-mobile", region: "global" });
  });

  it("infers nothing from a slug", () => {
    expect(resolveRegion("lone-ru", { region_code: "global", region_of: null })).toEqual({
      base: "lone-ru",
      region: "global",
    });
  });
});

describe("switcherRegions", () => {
  it("lists every region of a multi-region game, in API order", () => {
    expect(switcherRegions({ regions: MLBB_REGIONS })).toEqual(MLBB_REGIONS);
  });

  it("is empty for a one-region game or an older API", () => {
    expect(switcherRegions({ regions: [] })).toEqual([]);
    expect(switcherRegions({ regions: [{ code: "global", slug: "x" }] })).toEqual([]);
    expect(switcherRegions({})).toEqual([]);
    expect(switcherRegions(undefined)).toEqual([]);
  });
});

describe("regionBrandSlug", () => {
  it("switching region switches the brand the page talks to", () => {
    expect(regionBrandSlug(MLBB_REGIONS, "global", "mobile-legends")).toBe("mobile-legends");
    expect(regionBrandSlug(MLBB_REGIONS, "ru", "mobile-legends")).toBe("mobile-legends-ru");
    expect(regionBrandSlug(MLBB_REGIONS, "ph", "mobile-legends")).toBe("mobile-legends-ph");
  });

  it("falls back to the given slug when the region is not listed", () => {
    expect(regionBrandSlug([], "global", "pubg-mobile")).toBe("pubg-mobile");
    expect(regionBrandSlug(MLBB_REGIONS, "br", "mobile-legends-ph")).toBe("mobile-legends-ph");
  });
});

describe("regionLabel", () => {
  it("names a known region through the catalog", () => {
    expect(regionLabel("ru", translate)).toBe(translate("topup.region.ru"));
    expect(regionLabel("global", translate)).toBe(translate("topup.region.global"));
  });

  it("names the game's main region after Uzbekistan, and only the main one", () => {
    expect(regionLabel("global", translate, true)).toBe(translate("topup.regionHome.global"));
    expect(regionLabel("cis", translate, true)).toBe(translate("topup.regionHome.cis"));
    // Free Fire's global server is a region, not home.
    expect(regionLabel("global", translate, false)).toBe(translate("topup.region.global"));
    expect(regionLabel("cis", translate)).toBe(translate("topup.region.cis"));
    // A Free Fire region code with no home label keeps its plain name.
    expect(regionLabel("mysg", translate, true)).toBe(translate("topup.region.mysg"));
  });

  it("falls back to the uppercase code for an unknown region", () => {
    expect(regionLabel("kz", translate)).toBe("KZ");
  });
});

describe("isUncheckedAccount", () => {
  it("is true when the account fields carry no player check", () => {
    expect(isUncheckedAccount([{ check: null }, {}])).toBe(true);
  });

  it("is false when any field is checkable", () => {
    expect(isUncheckedAccount([{ check: { server_field: "zone_id" } }, {}])).toBe(false);
    expect(isUncheckedAccount([{ check: {} }])).toBe(false);
  });

  it("is false when nothing is asked", () => {
    expect(isUncheckedAccount([])).toBe(false);
  });
});
