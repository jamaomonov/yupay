// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { SkinCategoryBar } from "./SkinCategoryBar";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { SkinFacets, SkinQuery } from "@/lib/skins";

const facets: SkinFacets = {
  categories: [
    { value: "rifles", count: 10 },
    { value: "music-kits", count: 3 },
  ],
  weapons: [
    { value: "AK-47", count: 5 },
    { value: "AWP", count: 4 },
    { value: "Galil AR", count: 9 },
  ],
  exteriors: [],
  rarities: [],
};

function bar(query: SkinQuery) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinCategoryBar query={query} facets={facets} locale="ru" />
    </NextIntlClientProvider>,
  );
}

it("keeps a chosen weapon visible and clearable", () => {
  bar({ sort: "-price", category: "rifles", weapon: "AK-47" });
  const chip = screen.getByRole("link", { name: "AK-47" });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/skins?category=rifles");
});

it("lists every weapon of the category from the facets, in their order", () => {
  bar({ sort: "-price", category: "rifles" });
  const names = ["AK-47", "AWP", "Galil AR"].map((n) => screen.getByRole("link", { name: n }));
  expect(names).toHaveLength(3);
});

it("draws each category tile with its silhouette icon", () => {
  bar({ sort: "-price", category: "rifles" });
  const tile = screen.getByRole("link", { name: "Винтовки" });
  expect(tile).toHaveAttribute("aria-current", "page");
  const icon = tile.querySelector("[data-skin-icon]");
  expect(icon?.getAttribute("style")).toContain("/skins/categories/rifles.png");
  // Music kits have no item image — a glyph stands in.
  expect(screen.getByRole("link", { name: "Музыка" }).querySelector("svg")).not.toBeNull();
});
