import { describe, expect, it } from "vitest";

import {
  foldRegions,
  homeRegionFlagSrc,
  REGION_TOP,
  regionFlagCode,
  regionFlagSrc,
  regionMatches,
} from "./region-flag";

describe("regionFlagCode", () => {
  it("maps our codes and SKU spellings to ISO", () => {
    expect(regionFlagCode("us")).toBe("us");
    expect(regionFlagCode("US")).toBe("us");
    expect(regionFlagCode("uk")).toBe("gb");
    expect(regionFlagCode("MY/SG")).toBe("my");
    expect(regionFlagCode("eu")).toBe("eu");
  });

  it("has no flag for a region that is not one country", () => {
    // `usd` is Steam Wallet's global card («Глобальная (USD)»), not the US.
    for (const code of [
      "global",
      "GLOBAL",
      "cis",
      "mena",
      "latam",
      "SEA",
      "usd",
      "",
      null,
      undefined,
    ]) {
      expect(regionFlagCode(code)).toBeNull();
    }
  });
});

describe("flag paths", () => {
  it("points at the shipped SVG", () => {
    expect(regionFlagSrc("tr")).toBe("/flags/region/tr.svg");
    expect(regionFlagSrc("global")).toBeNull();
  });

  it("gives the game's home region our flag", () => {
    expect(homeRegionFlagSrc("global", true)).toBe("/flags/region/uz.svg");
    expect(homeRegionFlagSrc("cis", true)).toBe("/flags/region/uz.svg");
    expect(homeRegionFlagSrc("global", false)).toBeNull();
    expect(homeRegionFlagSrc("us", true)).toBe("/flags/region/us.svg");
  });
});

describe("foldRegions", () => {
  // PlayStation, in the API's order.
  const psn = [
    "us", "my", "sg", "id", "th", "tr", "br", "uk", "ca", "au", "nz", "jp", "hk", "ae", "sa",
    "za", "fr", "at", "ch", "dk", "no", "pl", "de", "it", "es", "nl", "be", "lu", "pt", "ie",
    "fi", "cz", "sk", "hu", "ro", "hr", "kw", "qa", "bh", "om", "lb", "in", "ar",
  ]; // prettier-ignore

  it("leaves a short list alone", () => {
    const few = ["global", "ru", "ph", "my", "sg", "id"];
    expect(foldRegions(few, "ru")).toEqual({ shown: few, folded: 0 });
  });

  it("keeps the main region first, then the popular countries", () => {
    const { shown, folded } = foldRegions(psn, "us");
    expect(shown).toEqual(["us", "tr", "uk", "de", "ae", "pl", "in", "sa"]);
    expect(folded).toBe(psn.length - REGION_TOP);
  });

  it("puts a region picked from the full list on the last chip", () => {
    const { shown } = foldRegions(psn, "es");
    expect(shown).toHaveLength(REGION_TOP);
    expect(shown[0]).toBe("us");
    expect(shown.at(-1)).toBe("es");
  });
});

describe("regionMatches", () => {
  it("finds by part of the name or the code start, ignoring case", () => {
    expect(regionMatches("тур", "Турция", "tr")).toBe(true);
    expect(regionMatches("ТУР", "Турция", "tr")).toBe(true);
    expect(regionMatches("tr", "Турция", "tr")).toBe(true);
    expect(regionMatches("герм", "Турция", "tr")).toBe(false);
    expect(regionMatches("  ", "Турция", "tr")).toBe(true);
  });
});
