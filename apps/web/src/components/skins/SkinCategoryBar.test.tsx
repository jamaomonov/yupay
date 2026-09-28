// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";

import { SkinCategoryBar } from "./SkinCategoryBar";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { SkinFacets } from "@/lib/skins";

const facets: SkinFacets = {
  categories: [{ value: "rifles", count: 10 }],
  weapons: [{ value: "AK-47", count: 5 }],
  exteriors: [],
  rarities: [],
};

it("keeps a chosen weapon visible and clearable even when the page holds only it", () => {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinCategoryBar
        query={{ sort: "popular", category: "rifles", weapon: "AK-47" }}
        facets={facets}
        locale="ru"
        items={[]}
      />
    </NextIntlClientProvider>,
  );
  const chip = screen.getByRole("link", { name: "AK-47" });
  expect(chip).toHaveAttribute("aria-current", "page");
  expect(chip).toHaveAttribute("href", "/skins?category=rifles");
});
