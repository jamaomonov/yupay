import { describe, expect, it } from "vitest";

import {
  methodVisibility,
  paymentProviderDisplay,
  providerStatusMap,
  selectActiveMethodId,
  type ProvidersOut,
} from "./payment-providers";

describe("paymentProviderDisplay", () => {
  it("maps click (and click_miniapp) to the Click brand + logo", () => {
    const click = { name: "Click", logo: "/payment/click.svg", logoWidth: 157, logoHeight: 40 };
    expect(paymentProviderDisplay("click")).toEqual(click);
    expect(paymentProviderDisplay("click_miniapp")).toEqual(click);
  });
  it("maps payme and uzum to their logos", () => {
    expect(paymentProviderDisplay("payme")).toEqual({
      name: "Payme",
      logo: "/payment/payme.png",
      logoWidth: 454,
      logoHeight: 179,
    });
    expect(paymentProviderDisplay("uzum")).toEqual({
      name: "Uzum",
      logo: "/payment/uzum.png",
      logoWidth: 506,
      logoHeight: 148,
    });
  });
  it("gives every logo its true aspect ratio, since callers scale by height", () => {
    // A wrong ratio here squashes the wordmark, which is the whole reason the
    // badge can drop the text beside it.
    for (const slug of ["click", "payme", "uzum"]) {
      const d = paymentProviderDisplay(slug);
      expect(d?.logoWidth).toBeGreaterThan(0);
      expect(d?.logoHeight).toBeGreaterThan(0);
    }
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

describe("selectActiveMethodId", () => {
  const methods = [
    { id: "click", provider: "click" },
    { id: "payme", provider: "payme" },
    { id: "uzum", provider: "uzum" },
  ];

  it("keeps the current selection when its provider is active", () => {
    const bySlug = providerStatusMap({ providers: [{ slug: "click", status: "active" }] });
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("click");
  });

  it("reselects the first active method when the hardcoded default is under maintenance", () => {
    const bySlug = providerStatusMap({
      providers: [
        { slug: "click", status: "maintenance" },
        { slug: "payme", status: "active" },
      ],
    });
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("payme");
  });

  it("reselects the first active method when the default is absent (admin-disabled)", () => {
    const bySlug = providerStatusMap({ providers: [{ slug: "uzum", status: "active" }] });
    expect(selectActiveMethodId(methods, "click", bySlug)).toBe("uzum");
  });

  it("returns null when no method is active, so nothing stays submittable", () => {
    const bySlug = providerStatusMap({
      providers: [
        { slug: "click", status: "maintenance" },
        { slug: "payme", status: "maintenance" },
      ],
    });
    expect(selectActiveMethodId(methods, "click", bySlug)).toBeNull();
  });
});
