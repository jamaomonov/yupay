import { describe, expect, it } from "vitest";

import { providerLabel } from "./OrderSuccess";

import { translate } from "@/lib/i18n/core";

describe("providerLabel", () => {
  it("maps click (and click_miniapp) to the Click brand name", () => {
    expect(providerLabel("click")).toBe("Click");
    expect(providerLabel("click_miniapp")).toBe("Click");
  });

  it("maps payme, uzum and octo to their brand names", () => {
    expect(providerLabel("payme")).toBe("Payme");
    expect(providerLabel("uzum")).toBe("Uzum");
    expect(providerLabel("octo")).toBe("Octo");
  });

  it("maps wallet to the localized balance label", () => {
    expect(providerLabel("wallet")).toBe(translate("success.paidWithWallet"));
  });

  it("renders an unknown slug as-is and null/empty as null", () => {
    expect(providerLabel("mock")).toBe("mock");
    expect(providerLabel(null)).toBeNull();
    expect(providerLabel("")).toBeNull();
  });
});
