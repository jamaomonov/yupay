import { describe, expect, it } from "vitest";

import { parseSkinQuery, skinQueryString } from "./skins";

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
      sort: "popular",
      maxUzs: 150000,
      stattrak: true,
      q: "redline",
    });
  });

  it("drops an unknown category and exterior", () => {
    expect(parseSkinQuery({ category: "../admin", exterior: "XX" })).toEqual({ sort: "popular" });
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
    expect(skinQueryString({ sort: "popular", weapon: "AWP", category: "rifles" })).toBe(
      "?category=rifles&weapon=AWP",
    );
    expect(skinQueryString({ sort: "popular" })).toBe("");
    expect(skinQueryString({ sort: "price" })).toBe("?sort=price");
  });

  it("resets the cursor when a filter changes", () => {
    expect(skinQueryString({ sort: "popular", cursor: "abc" }, { exterior: "MW" })).toBe(
      "?exterior=MW",
    );
    expect(skinQueryString({ sort: "popular" }, { cursor: "abc" })).toBe("?cursor=abc");
  });
});
