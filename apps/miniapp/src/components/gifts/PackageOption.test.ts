import { describe, expect, test } from "vitest";

import { priceLabel } from "./PackageOption";

import { formatMoney } from "@/lib/currency";

// FX-down parity fix (2026-09-04 review): `price_uzs` legitimately comes
// back `null` when FX is unavailable, and this must never fall back to
// quoting the USD figure — a buyer reading a dollar amount here would tap
// Buy and be sent to a UZS-only acquirer for a sum they never saw. The
// `unavailable` placeholder is what both call sites (`PackageOption`'s own
// price tag, `GiftGame`'s big price row) already pass for "no price at
// all"; an FX-down price degrades to the exact same placeholder rather than
// a second, differently-worded fallback.
describe("priceLabel", () => {
  test("renders the UZS figure when it's known", () => {
    expect(priceLabel({ price_usd: "12.99", price_uzs: "165000" }, "—")).toBe(
      formatMoney(165_000, "UZS"),
    );
  });

  test("never falls back to the USD figure when price_uzs is null (FX down)", () => {
    expect(priceLabel({ price_usd: "12.99", price_uzs: null }, "—")).toBe("—");
  });

  test("renders the unavailable placeholder when there's no price at all", () => {
    expect(priceLabel(null, "—")).toBe("—");
  });
});
