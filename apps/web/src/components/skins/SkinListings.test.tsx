// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkinListings } from "./SkinListings";
import { SkinOffersProvider } from "./SkinOffers";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type * as SkinsModule from "@/lib/skins";

import { fetchSkinListings } from "@/lib/skins";

vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));
const mocked = vi.mocked(fetchSkinListings);

function renderListings() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinOffersProvider slug="ak-ft">
        <SkinListings
          locale="ru"
          exterior="FT"
          image="https://community.fastly.steamstatic.com/economy/image/ak"
        />
      </SkinOffersProvider>
    </NextIntlClientProvider>,
  );
}

describe("SkinListings", () => {
  beforeEach(() => {
    mocked.mockReset();
  });

  it("renders live listings with float, seed and inspect", async () => {
    mocked.mockResolvedValue({
      degraded: false,
      items: [
        {
          listing_id: 1,
          price_usd: "30.37",
          price_uzs: "385700",
          float_value: 0.3692,
          paint_seed: 421,
          stickers: [
            {
              name: "Sticker | X",
              image: "https://community.fastly.steamstatic.com/economy/image/s",
              slot: 1,
              wear: null,
            },
          ],
          inspect_url: "steam://rungame/730/1/+csgo_econ_action_preview%20S1A1D1",
        },
      ],
    });
    const { container } = renderListings();
    expect(await screen.findByText("0.3692")).toBeInTheDocument();
    // Each row says which wear it is and shows the skin, as a market row does.
    expect(screen.getByText("FT")).toBeInTheDocument();
    expect(container.querySelector('img[src*="economy/image/ak"]')).not.toBeNull();
    expect(screen.getByText("421")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Осмотр/ })).toHaveAttribute(
      "href",
      expect.stringMatching(/^steam:\/\//),
    );
    // Stickers are thumbnails named for screen readers, not a comma-joined string.
    expect(screen.getByRole("img", { name: "Sticker | X" })).toBeInTheDocument();
    // Every offer we sell is instant: said once by the price, not on each row.
    expect(screen.queryByText("Мгновенно")).not.toBeInTheDocument();
  });

  it("shows prices without float or inspect when degraded, and no service note", async () => {
    mocked.mockResolvedValue({
      degraded: true,
      items: [
        {
          listing_id: 1,
          price_usd: "30.37",
          price_uzs: "385700",
          float_value: null,
          paint_seed: null,
          stickers: [],
          inspect_url: null,
        },
      ],
    });
    renderListings();
    expect(await screen.findByText(/385\s?700/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Осмотр/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/обновля/)).not.toBeInTheDocument();
  });

  it("says there are no offers on an error or an empty list", async () => {
    mocked.mockRejectedValue(new Error("down"));
    renderListings();
    expect(await screen.findByText("Сейчас нет предложений")).toBeInTheDocument();
  });
});

describe("SkinListings with buying on", () => {
  it("lets a row's «Купить» pick that offer", async () => {
    mocked.mockResolvedValue({
      degraded: false,
      items: [
        {
          listing_id: 1,
          price_usd: "30.00",
          price_uzs: "381000",
          float_value: 0.2,
          paint_seed: 1,
          stickers: [],
          inspect_url: null,
        },
        {
          listing_id: 2,
          price_usd: "31.00",
          price_uzs: "393700",
          float_value: 0.3,
          paint_seed: 2,
          stickers: [],
          inspect_url: null,
        },
      ],
    });
    render(
      <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
        <SkinOffersProvider slug="ak-ft">
          <SkinListings locale="ru" buyable />
        </SkinOffersProvider>
      </NextIntlClientProvider>,
    );
    const buttons = await screen.findAllByRole("button", { name: "Купить" });
    expect(screen.getByRole("button", { name: "Выбран" })).toBeInTheDocument();
    fireEvent.click(buttons[0]!);
    expect(screen.getAllByRole("button", { name: "Выбран" })).toHaveLength(1);
  });
});
