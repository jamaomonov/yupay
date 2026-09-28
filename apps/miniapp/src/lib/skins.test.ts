import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSkinDetail, fetchSkinFacets, skinPriceText, skinsApiParams } from "./skins";

function answer(status: number, body: unknown = {}): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status }))),
  );
}

describe("skinPriceText", () => {
  it("prints soʻm, falls back to dollars, null only without a price", () => {
    expect(skinPriceText("385700", "30.37")).toMatch(/385.?700/);
    expect(skinPriceText(null, "30.37")).toMatch(/30[.,]37/);
    expect(skinPriceText(null, null)).toBeNull();
  });
});

describe("skinsApiParams", () => {
  it("maps the query to API params", () => {
    expect(
      skinsApiParams({ sort: "price", category: "rifles", minUzs: 1000, stattrak: true }),
    ).toBe("category=rifles&stattrak=true&min_uzs=1000&sort=price&limit=24");
  });
});

describe("fetchers", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("facets are null while the feature is off (404)", async () => {
    answer(404);
    await expect(fetchSkinFacets()).resolves.toBeNull();
  });

  it("facets throw on an outage", async () => {
    answer(503);
    await expect(fetchSkinFacets()).rejects.toThrow("503");
  });

  it("detail is null on 404 and throws on an outage", async () => {
    answer(404);
    await expect(fetchSkinDetail("x")).resolves.toBeNull();
    answer(503);
    await expect(fetchSkinDetail("x")).rejects.toThrow("503");
  });

  it("facets are scoped to the chosen category", async () => {
    answer(200, { categories: [], weapons: [], exteriors: [], rarities: [] });
    await fetchSkinFacets("rifles");
    const url = vi.mocked(fetch).mock.calls[0]?.[0] as string; // api() passes a string URL
    expect(url).toContain("/api/v1/skins/facets?category=rifles");
  });
});
