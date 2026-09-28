// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { SkinPriceBlock } from "./SkinPriceBlock";
import { SkinWearTiles } from "./SkinWearTiles";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { SkinFamilyMember } from "@/lib/skins";
import type { ReactNode } from "react";

const wrap = (ui: ReactNode) =>
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      {ui}
    </NextIntlClientProvider>,
  );

const family: SkinFamilyMember[] = [
  {
    slug: "ak-mw",
    exterior: "MW",
    stattrak: false,
    souvenir: false,
    price_usd: "60.00",
    price_uzs: "762000",
    count: 12,
  },
  {
    slug: "ak-ft",
    exterior: "FT",
    stattrak: false,
    souvenir: false,
    price_usd: "30.21",
    price_uzs: "383700",
    count: 422,
  },
  {
    slug: "st-ak-ft",
    exterior: "FT",
    stattrak: true,
    souvenir: false,
    price_usd: null,
    price_uzs: null,
    count: 0,
  },
];

describe("SkinWearTiles", () => {
  it("links every wear, marks the current one, says sold out without a price", () => {
    wrap(<SkinWearTiles family={family} current="ak-ft" locale="ru" />);
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/skins/ak-mw",
      "/skins/ak-ft",
      "/skins/st-ak-ft",
    ]);
    expect(links[1]).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
    expect(screen.getByText(/383\s?700/)).toBeInTheDocument();
  });

  it("renders nothing for a lone item", () => {
    const { container } = wrap(
      <SkinWearTiles family={family.slice(0, 1)} current="ak-mw" locale="ru" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SkinPriceBlock", () => {
  it("shows the price and a disabled buy button", () => {
    wrap(
      <SkinPriceBlock
        priceUzs="383700"
        priceUsd="30.21"
        steamUrl="https://steamcommunity.com/market/listings/730/x"
        locale="ru"
      />,
    );
    expect(screen.getByText(/383\s?700/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Покупка скоро" })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Steam/ })).toHaveAttribute(
      "rel",
      expect.stringContaining("nofollow"),
    );
  });

  it("says sold out when there is no price", () => {
    wrap(
      <SkinPriceBlock
        priceUzs={null}
        priceUsd={null}
        steamUrl="https://steamcommunity.com/market/listings/730/x"
        locale="ru"
      />,
    );
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
  });
});
