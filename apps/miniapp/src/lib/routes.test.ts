import { describe, expect, it } from "vitest";

import { hrefForGameSlug } from "./routes";

describe("hrefForGameSlug", () => {
  it("sends the CS2 skins brand to its market, not a top-up form", () => {
    expect(hrefForGameSlug("cs2-skins")).toBe("/cs2-market");
  });

  it("keeps Steam Gifts on its own flow and every other brand on /topup", () => {
    expect(hrefForGameSlug("steam-gifts")).toBe("/gifts");
    expect(hrefForGameSlug("pubg-mobile")).toBe("/topup/pubg-mobile");
  });
});
