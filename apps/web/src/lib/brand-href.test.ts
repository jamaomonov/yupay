import { describe, expect, it } from "vitest";

import { brandPath, CS2_SKINS_BRAND } from "./brand-href";

describe("brandPath", () => {
  it("sends the CS2 skins brand to the skins market", () => {
    expect(brandPath(CS2_SKINS_BRAND)).toBe("/skins");
  });

  it("keeps every other brand on its store page", () => {
    expect(brandPath("pubg-mobile")).toBe("/store/pubg-mobile");
  });
});
