// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { SkinSearch } from "./SkinSearch";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import { apiFetch } from "@/lib/client";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/client", () => ({ apiFetch: vi.fn() }));

it("suggests skins with their picture, wear and price", async () => {
  vi.mocked(apiFetch).mockResolvedValue({
    items: [
      {
        slug: "awp-asiimov-ww",
        name: "AWP | Asiimov (Well-Worn)",
        phase: null,
        category: "rifles",
        weapon: "AWP",
        skin: "Asiimov",
        exterior: "WW",
        stattrak: false,
        souvenir: false,
        rarity: "Covert",
        rarity_color: "#eb4b4b",
        image_url: "https://community.fastly.steamstatic.com/economy/image/awp",
        price_usd: "80.00",
        price_uzs: "1016000",
        steam_price_usd: null,
        discount_percent: null,
        count: 30,
        min_float: null,
        max_float: null,
      },
    ],
  });
  const { container } = render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinSearch initial="" locale="ru" query={{ sort: "-price" }} />
    </NextIntlClientProvider>,
  );
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "as" } });
  expect(await screen.findByText("Asiimov")).toBeInTheDocument();
  expect(screen.getByText("WW")).toBeInTheDocument();
  expect(screen.getByText(/1\s?016\s?000/)).toBeInTheDocument();
  expect(container.querySelector('img[src*="economy/image/awp"]')).not.toBeNull();
});
