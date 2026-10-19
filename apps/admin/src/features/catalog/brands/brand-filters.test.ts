import { describe, expect, it } from "vitest";

import { filterBrands, parseFlagFilter } from "./brand-filters";

import type { Brand } from "../types";

function brand(slug: string, active: boolean, retail: boolean, b2b: boolean): Brand {
  return {
    id: slug,
    slug,
    category_id: "c",
    logo_url: null,
    hero_image_url: null,
    accent_color: null,
    sort_order: 0,
    active,
    maintenance: false,
    visible_b2b: b2b,
    visible_retail: retail,
    translations: [],
  };
}

const ALL = [
  brand("both", true, true, true),
  brand("retail-only", true, true, false),
  brand("reseller-only", true, false, true),
  brand("off", false, true, true),
];

const slugs = (bs: Brand[]) => bs.map((b) => b.slug);

describe("filterBrands", () => {
  it("returns everything with no filter set", () => {
    expect(slugs(filterBrands(ALL, { active: "", retail: "", b2b: "" }))).toEqual(slugs(ALL));
  });

  it("searches the slug and the names, on top of the flags", () => {
    const pubg = brand("pubg-mobile", true, true, true);
    const named: Brand = {
      ...brand("mlbb", true, true, false),
      translations: [{ locale: "ru", name: "Mobile Legends" }],
    };
    const list = [...ALL, pubg, named];
    const none = { active: "", retail: "", b2b: "" } as const;
    expect(slugs(filterBrands(list, { ...none, query: "PUBG" }))).toEqual(["pubg-mobile"]);
    expect(slugs(filterBrands(list, { ...none, query: "legends" }))).toEqual(["mlbb"]);
    expect(slugs(filterBrands(list, { ...none, b2b: "yes", query: "legends" }))).toEqual([]);
  });

  it("filters by status", () => {
    expect(slugs(filterBrands(ALL, { active: "no", retail: "", b2b: "" }))).toEqual(["off"]);
  });

  it("finds reseller-only brands by combining storefront and merchants", () => {
    expect(slugs(filterBrands(ALL, { active: "yes", retail: "no", b2b: "yes" }))).toEqual([
      "reseller-only",
    ]);
  });

  it("finds brands hidden from merchants", () => {
    expect(slugs(filterBrands(ALL, { active: "", retail: "", b2b: "no" }))).toEqual([
      "retail-only",
    ]);
  });
});

describe("parseFlagFilter", () => {
  it("keeps yes/no and drops anything else", () => {
    expect(parseFlagFilter("yes")).toBe("yes");
    expect(parseFlagFilter("no")).toBe("no");
    expect(parseFlagFilter("maybe")).toBe("");
  });
});
