import { afterEach, describe, expect, test } from "vitest";

import { cardPriceLabel, priceText } from "./GiftsCatalog";

import type { GiftApp } from "@/lib/gifts";

import { setActiveLocale } from "@/lib/i18n/core";

/**
 * The catalogue card price. Node-env only (no jsdom/RTL in this app) — the
 * pure formatting/prefix pieces are what's directly testable, mirroring how
 * `GiftCatalogCard` actually composes them.
 */

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

afterEach(() => {
  setActiveLocale("ru");
});

describe("priceText", () => {
  test("prefers the UZS reference price when known", () => {
    expect(priceText(makeApp({ price_uzs: "125000", price_usd: "9.99" }))).toContain("125");
  });

  test("falls back to USD only when no UZS reference price exists at all", () => {
    const out = priceText(makeApp({ price_uzs: null, price_usd: "9.99" }));
    expect(out).not.toBeNull();
    expect(out).toContain("9");
  });

  test("null when the catalog has no price in either currency", () => {
    expect(priceText(makeApp({ price_uzs: null, price_usd: null }))).toBeNull();
  });
});

/**
 * A catalogue row is the *default-zone reference* price, never the
 * per-package, per-country figure the game page actually computes
 * (`gifts/routes.py` documents this) — the «от»/"from"/"dan" prefix is what
 * keeps a 1 250 000 → 1 410 000 jump from reading as bait (2026-09-04
 * review).
 */
describe("cardPriceLabel", () => {
  test("prefixes a known price with the given from-word", () => {
    expect(cardPriceLabel(makeApp({ price_uzs: "125000" }), "от")).toBe(
      `от ${String(priceText(makeApp({ price_uzs: "125000" })))}`,
    );
  });

  test("null (no price row at all) when the app has no price", () => {
    expect(cardPriceLabel(makeApp({ price_uzs: null, price_usd: null }), "от")).toBeNull();
  });

  test("carries the localized UZS word through the prefix", () => {
    setActiveLocale("uz");
    const label = cardPriceLabel(makeApp({ price_uzs: "125000" }), "dan");
    // `Intl`'s uz grouping separator is U+00A0 (NBSP) — normalize before
    // comparing against a plain-space literal.
    expect(label?.replace(/\u00a0/g, " ")).toBe("dan 125 000 so\u02bbm");
  });
});
