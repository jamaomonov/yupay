import { expect, it } from "vitest";

import { activeNavHref, primaryNavLinks } from "./primary-nav";

it("orders the header by what visitors come for, skins only while on", () => {
  expect(primaryNavLinks("ru", true).map((l) => l.key)).toEqual([
    "steam",
    "skins",
    "store",
    "blog",
  ]);
  expect(primaryNavLinks("ru", false).map((l) => l.key)).toEqual(["steam", "store", "blog"]);
});

it("marks only the Steam link on the Steam page, the catalogue on another brand", () => {
  const links = primaryNavLinks("ru", true);
  expect(activeNavHref("/store/steam", links)).toBe("/store/steam");
  expect(activeNavHref("/store/pubg-mobile", links)).toBe("/store");
  expect(activeNavHref("/", links)).toBeUndefined();
});
