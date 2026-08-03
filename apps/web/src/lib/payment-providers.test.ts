import { describe, expect, it } from "vitest";

import {
  methodVisibility,
  paymentProviderDisplay,
  providerStatusMap,
  type ProvidersOut,
} from "./payment-providers";

describe("paymentProviderDisplay", () => {
  it("maps click (and click_miniapp) to the Click brand + logo", () => {
    expect(paymentProviderDisplay("click")).toEqual({ name: "Click", logo: "/payment/click.svg" });
    expect(paymentProviderDisplay("click_miniapp")).toEqual({
      name: "Click",
      logo: "/payment/click.svg",
    });
  });
  it("maps payme and uzum to their logos", () => {
    expect(paymentProviderDisplay("payme")).toEqual({ name: "Payme", logo: "/payment/payme.png" });
    expect(paymentProviderDisplay("uzum")).toEqual({ name: "Uzum", logo: "/payment/uzum.png" });
  });
  it("maps octo to a text badge (no logo asset)", () => {
    expect(paymentProviderDisplay("octo")).toEqual({ name: "Octo" });
  });
  it("maps wallet to a localizable label key", () => {
    expect(paymentProviderDisplay("wallet")).toEqual({ nameKey: "paidWithWallet" });
  });
  it("renders an unknown slug as plain text and null as null", () => {
    expect(paymentProviderDisplay("mock")).toEqual({ name: "mock" });
    expect(paymentProviderDisplay(null)).toBeNull();
  });
});

describe("providerStatusMap + methodVisibility", () => {
  // One active, one under maintenance, one omitted entirely (admin-disabled).
  const payload: ProvidersOut = {
    providers: [
      { slug: "click", status: "active" },
      { slug: "payme", status: "maintenance" },
    ],
  };
  const bySlug = providerStatusMap(payload);

  it("keeps an active provider selectable", () => {
    expect(methodVisibility("click", bySlug)).toBe("active");
  });

  it("flags a maintenance provider as non-clickable but still rendered", () => {
    expect(methodVisibility("payme", bySlug)).toBe("maintenance");
  });

  it("hides a provider slug absent from the response entirely", () => {
    expect(methodVisibility("uzum", bySlug)).toBe("hidden");
  });

  it("fails open (treats every method as active) before the fetch resolves", () => {
    expect(methodVisibility("click", null)).toBe("active");
    expect(methodVisibility("uzum", null)).toBe("active");
  });
});
