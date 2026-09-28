// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { SkinHero } from "./SkinHero";
import { SkinOffersProvider } from "./SkinOffers";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type * as SkinsModule from "@/lib/skins";

import { fetchSkinListings } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));

const lot = (id: number, usd: string, float: number, stickers: number) => ({
  listing_id: id,
  price_usd: usd,
  price_uzs: null,
  float_value: float,
  paint_seed: 7,
  stickers: Array.from({ length: stickers }, (_, i) => ({
    name: `Sticker | ${String(i)}`,
    image: `https://community.fastly.steamstatic.com/economy/image/s${String(i)}`,
    slot: i,
    wear: null,
  })),
  inspect_url: "steam://rungame/730/1/+csgo_econ_action_preview%20S1A1D1",
});

function hero() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinOffersProvider slug="ak">
        <SkinHero
          image="https://x/economy/image/ak"
          name="AK-47 | Redline"
          exterior="FT"
          rarityColor={null}
        />
      </SkinOffersProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchSkinListings).mockResolvedValue({
    degraded: false,
    items: [lot(2, "31.00", 0.2, 0), lot(1, "30.00", 0.3692, 3)],
  });
});

it("shows the picked offer's float, wear, stickers and inspect on the picture", async () => {
  hero();
  expect(await screen.findByText("0.3692")).toBeInTheDocument();
  expect(screen.getByText("FT")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Sticker | 2" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Осмотр/ })).toHaveAttribute(
    "href",
    expect.stringContaining("steam://"),
  );
});
