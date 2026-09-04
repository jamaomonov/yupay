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

/**
 * "1 издание · 0 DLC" was printed on almost every card — true of the vast
 * majority of the ~4k-game catalog — which made it noise rather than
 * information (2026-09-04 review). It only earns its line once there's an
 * actual choice: more than one edition, or at least one DLC.
 */
it("hides the editions/DLC counter for the common single-edition, no-DLC case", () => {
  render(<GiftCard app={makeApp({ packages_count: 1, dlc_count: 0 })} locale="ru" />);

  expect(screen.queryByText(/card\.editions/)).not.toBeInTheDocument();
  expect(screen.queryByText(/card\.dlc/)).not.toBeInTheDocument();
});

it("shows the counter once there is more than one edition", () => {
  render(<GiftCard app={makeApp({ packages_count: 2, dlc_count: 0 })} locale="ru" />);

  expect(screen.getByText(/card\.editions/)).toBeInTheDocument();
});

it("shows the counter once the app has at least one DLC", () => {
  render(<GiftCard app={makeApp({ packages_count: 1, dlc_count: 3 })} locale="ru" />);

  expect(screen.getByText(/card\.dlc/)).toBeInTheDocument();
});
