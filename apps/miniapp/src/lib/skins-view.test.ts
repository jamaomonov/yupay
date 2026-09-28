import { describe, expect, it } from "vitest";

import type { SkinItem } from "@yupay/utils";

import { accumulateSkins, visibleWeapons } from "./skins-view";

const item = (slug: string) => ({ slug }) as SkinItem; // only the key matters here

describe("accumulateSkins", () => {
  it("appends the next page and drops duplicates", () => {
    const out = accumulateSkins([item("a"), item("b")], [item("b"), item("c")], true);
    expect(out.map((i) => i.slug)).toEqual(["a", "b", "c"]);
  });

  it("a first page replaces", () => {
    const out = accumulateSkins([item("a")], [item("z")], false);
    expect(out.map((i) => i.slug)).toEqual(["z"]);
  });
});

describe("visibleWeapons", () => {
  const rifles = {
    categories: [],
    weapons: [{ value: "AK-47", count: 5 }],
    exteriors: [],
    rarities: [],
  };

  it("shows nothing while the facets still describe another category", () => {
    // Tapped «Пистолеты»; the rifles facets are still in hand until the new ones land.
    expect(
      visibleWeapons(
        { sort: "-price", category: "pistols" },
        { category: "rifles", facets: rifles },
      ),
    ).toEqual([]);
  });

  it("lists the category's weapons and keeps a chosen one", () => {
    expect(
      visibleWeapons(
        { sort: "-price", category: "rifles" },
        { category: "rifles", facets: rifles },
      ),
    ).toEqual(["AK-47"]);
    expect(
      visibleWeapons(
        { sort: "-price", category: "rifles", weapon: "AWP" },
        { category: "rifles", facets: rifles },
      ),
    ).toEqual(["AWP", "AK-47"]);
  });

  it("is empty without a category", () => {
    expect(visibleWeapons({ sort: "-price" }, { category: undefined, facets: rifles })).toEqual([]);
  });
});
