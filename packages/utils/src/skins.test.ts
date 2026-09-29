import { describe, expect, it } from "vitest";

import { filterSections, parseSkinQuery, skinQueryString } from "./skins";

import type { SkinFacets } from "./skins";

describe("parseSkinQuery", () => {
  it("keeps known values and whitelists the rest", () => {
    const q = parseSkinQuery({
      category: "rifles",
      weapon: "AK-47",
      exterior: "FT",
      sort: "evil",
      min: "abc",
      max: "150000",
      cursor: "%%%",
      stattrak: "1",
      q: "  redline  ",
    });
    expect(q).toEqual({
      category: "rifles",
      weapon: "AK-47",
      exterior: "FT",
      sort: "-price",
      maxUzs: 150000,
      stattrak: true,
      q: "redline",
    });
  });

  it("drops an unknown category and exterior", () => {
    expect(parseSkinQuery({ category: "../admin", exterior: "XX" })).toEqual({ sort: "-price" });
  });

  it("takes the first value of a repeated param", () => {
    expect(parseSkinQuery({ weapon: ["AWP", "AK-47"] }).weapon).toBe("AWP");
  });

  it("accepts a well-formed cursor", () => {
    expect(parseSkinQuery({ cursor: "WzEsImEiXQ" }).cursor).toBe("WzEsImEiXQ");
  });
});

describe("skinQueryString", () => {
  it("drops defaults, keeps a stable order", () => {
    expect(skinQueryString({ sort: "-price", weapon: "AWP", category: "rifles" })).toBe(
      "?category=rifles&weapon=AWP",
    );
    expect(skinQueryString({ sort: "-price" })).toBe("");
    expect(skinQueryString({ sort: "price" })).toBe("?sort=price");
  });

  it("resets the cursor when a filter changes", () => {
    expect(skinQueryString({ sort: "-price", cursor: "abc" }, { exterior: "MW" })).toBe(
      "?exterior=MW",
    );
    expect(skinQueryString({ sort: "-price" }, { cursor: "abc" })).toBe("?cursor=abc");
  });
});

describe("filterSections", () => {
  const facets = (rarities: string[], exteriors = 5): SkinFacets => ({
    categories: [],
    weapons: [],
    exteriors: Array.from({ length: exteriors }, (_, i) => ({ value: `E${String(i)}`, count: 1 })),
    rarities: rarities.map((value) => ({ value, count: 1, color: null })),
  });
  const ALL = [
    "Contraband",
    "Covert",
    "Extraordinary",
    "Master",
    "Classified",
    "Exotic",
    "Restricted",
    "High Grade",
    "Mil-Spec Grade",
    "Base Grade",
    "Industrial Grade",
    "Consumer Grade",
  ];

  it("offers the weapon rarity scale when no category is picked, as the markets do", () => {
    const s = filterSections(undefined, facets(ALL), undefined);
    expect(s.rarities.map((r) => r.value)).toEqual([
      "Contraband",
      "Covert",
      "Classified",
      "Restricted",
      "Mil-Spec Grade",
      "Industrial Grade",
      "Consumer Grade",
    ]);
    expect(s.wear).toBe(true);
    expect(s.stattrak).toBe(true);
  });

  it("keeps a rarity already chosen from a link, even off that scale", () => {
    const s = filterSections(undefined, facets(ALL), "Master");
    expect(s.rarities.map((r) => r.value)).toContain("Master");
  });

  it("gives a category its own rarities and only the filters it has", () => {
    const agents = filterSections("agents", facets(["Master", "Superior"], 0), undefined);
    expect(agents.rarities.map((r) => r.value)).toEqual(["Master", "Superior"]);
    expect(agents.wear).toBe(false);
    expect(agents.stattrak).toBe(false);

    const gloves = filterSections("gloves", facets(["Extraordinary"]), undefined);
    expect(gloves.wear).toBe(true);
    expect(gloves.stattrak).toBe(false);

    expect(filterSections("knives", facets(["Covert"]), undefined).stattrak).toBe(true);
    expect(filterSections("music-kits", facets(["High Grade"], 0), undefined).stattrak).toBe(true);
    expect(filterSections("cases", facets(["Base Grade"], 0), undefined).stattrak).toBe(false);
  });
});

describe("team", () => {
  it("reads and writes an agent's side, and ignores anything else", () => {
    expect(parseSkinQuery({ category: "agents", team: "ct" }).team).toBe("ct");
    expect(parseSkinQuery({ team: "zz" }).team).toBeUndefined();
    expect(skinQueryString({ sort: "-price", category: "agents", team: "t" })).toBe(
      "?category=agents&team=t",
    );
  });

  it("offers the side filter only where the facets have sides", () => {
    const base = { categories: [], weapons: [], exteriors: [], rarities: [] };
    expect(
      filterSections("agents", { ...base, teams: [{ value: "ct", count: 1 }] }, undefined).team,
    ).toBe(true);
    expect(filterSections("rifles", { ...base, teams: [] }, undefined).team).toBe(false);
    expect(filterSections("rifles", base, undefined).team).toBe(false);
  });
});
