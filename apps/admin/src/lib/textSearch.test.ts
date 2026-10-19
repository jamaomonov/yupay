import { describe, expect, it } from "vitest";

import { matchesText } from "./textSearch";

describe("matchesText", () => {
  it("matches everything on an empty query", () => {
    expect(matchesText("  ", ["PUBG Mobile"])).toBe(true);
  });

  it("ignores case and folds ё", () => {
    expect(matchesText("pubg", ["PUBG Mobile"])).toBe(true);
    expect(matchesText("ёлка", ["Елка"])).toBe(true);
  });

  it("needs every word, in any field", () => {
    expect(matchesText("mobile pubg", ["PUBG Mobile", "pubg-mobile"])).toBe(true);
    expect(matchesText("pubg legends", ["PUBG Mobile"])).toBe(false);
    expect(matchesText("uc pubg", ["60 UC", "PUBG Mobile"])).toBe(true);
  });

  it("skips empty fields", () => {
    expect(matchesText("x", [null, undefined, ""])).toBe(false);
  });
});
