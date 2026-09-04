// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { GiftCard } from "./GiftCard";

import type { GiftApp } from "@/lib/gifts";

/**
 * The catalogue card price is the *default-zone reference* price
 * (`gifts/routes.py` documents this), never the per-package, per-country
 * figure the game page actually computes — a buyer who taps in at
 * 1 250 000 can land on a different number. The «от»/"from"/"dan" prefix
 * (2026-09-04 review) is what keeps that gap from reading as bait.
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string, values?: Record<string, unknown>) =>
    values ? `${k}:${JSON.stringify(values)}` : k,
}));

function makeApp(overrides: Partial<GiftApp> = {}): GiftApp {
  return {
    app_id: 1,
    name: "Steam Game",
    image: null,
    type: "game",
    price_usd: "9.99",
    price_uzs: "125000",
    discount_percent: null,
    packages_count: 1,
    dlc_count: 0,
    ...overrides,
  };
}

it('prefixes the catalogue card price with "from" — it is a reference price, not the buyable one', () => {
  render(<GiftCard app={makeApp({ price_uzs: "125000" })} locale="ru" />);

  // The `next-intl` mock is namespace-blind and echoes the key — "from" is
  // `web.store.from`'s key-as-value under this mock.
  expect(screen.getByText("from")).toBeInTheDocument();
});

it("renders no price row at all when the catalog has no UZS reference price", () => {
  render(<GiftCard app={makeApp({ price_uzs: null })} locale="ru" />);

  expect(screen.queryByText("from")).not.toBeInTheDocument();
});
