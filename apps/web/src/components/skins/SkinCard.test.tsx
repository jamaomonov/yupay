// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { SkinCard } from "./SkinCard";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { SkinItem } from "@/lib/skins";

const item: SkinItem = {
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Redline",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  rarity: "Classified",
  rarity_color: "#d32ce6",
  image_url: "https://community.akamai.steamstatic.com/economy/image/x",
  price_usd: "30.37",
  price_uzs: "385700",
  steam_price_usd: "43.794",
  discount_percent: 31,
  count: 49,
  min_float: "0.1",
  max_float: "0.7",
};

function renderCard(over: Partial<SkinItem> = {}) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinCard item={{ ...item, ...over }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("SkinCard", () => {
  it("shows skin, weapon, wear, price in som, lot count and discount", () => {
    renderCard();
    expect(screen.getByText("Redline")).toBeInTheDocument();
    expect(screen.getByText(/AK-47/)).toBeInTheDocument();
    expect(screen.getByText("FT")).toBeInTheDocument();
    expect(screen.getByText(/385\s?700/)).toBeInTheDocument();
    expect(screen.getByText("×49")).toBeInTheDocument();
    expect(screen.getByText("−31%")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/skins/ak-47-redline-field-tested");
  });

  it("marks StatTrak and hides a missing discount", () => {
    renderCard({ stattrak: true, discount_percent: null });
    expect(screen.getByText("StatTrak™")).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("says sold out without a price", () => {
    renderCard({ price_uzs: null, price_usd: null, count: 0 });
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
  });
});

describe("SkinCard without an FX rate", () => {
  it("shows the dollar price instead of calling an in-stock item sold out", () => {
    renderCard({ price_uzs: null, price_usd: "30.37" });
    expect(screen.getByText("$30.37")).toBeInTheDocument();
    expect(screen.queryByText("Нет в наличии")).not.toBeInTheDocument();
  });
});
