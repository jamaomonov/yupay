import { describe, expect, it } from "vitest";

import { baseSlug, hasRuTwin, mergeRegions, regionSlug, splitRegion } from "./region";

const SLUGS = [
  "pubg-mobile",
  "mobile-legends",
  "mobile-legends-ru",
  "magic-chess-gogo",
  "magic-chess-gogo-ru",
];

describe("region slugs", () => {
  it("strips the -ru suffix and nothing else", () => {
    expect(baseSlug("mobile-legends-ru")).toBe("mobile-legends");
    expect(baseSlug("mobile-legends")).toBe("mobile-legends");
    expect(baseSlug("pubg-russia")).toBe("pubg-russia");
  });

  it("knows which bases have a RU twin", () => {
    expect(hasRuTwin("mobile-legends", SLUGS)).toBe(true);
    expect(hasRuTwin("pubg-mobile", SLUGS)).toBe(false);
  });

  it("builds the region's brand slug", () => {
    expect(regionSlug("mobile-legends", "global")).toBe("mobile-legends");
    expect(regionSlug("mobile-legends", "ru")).toBe("mobile-legends-ru");
  });

  it("splits a deep-linked slug into base + region only when the base is a real brand", () => {
    expect(splitRegion("mobile-legends-ru", SLUGS)).toEqual({
      base: "mobile-legends",
      region: "ru",
    });
    expect(splitRegion("mobile-legends", SLUGS)).toEqual({
      base: "mobile-legends",
      region: "global",
    });
    // a brand whose slug merely ends in -ru with no base brand stays itself
    expect(splitRegion("lone-ru", ["lone-ru"])).toEqual({ base: "lone-ru", region: "global" });
  });

  it("hides RU twins whose base is listed, keeps everything else in order", () => {
    const games = SLUGS.map((slug) => ({ slug }));
    expect(mergeRegions(games).map((g) => g.slug)).toEqual([
      "pubg-mobile",
      "mobile-legends",
      "magic-chess-gogo",
    ]);
    expect(mergeRegions([{ slug: "lone-ru" }]).map((g) => g.slug)).toEqual(["lone-ru"]);
  });
});
