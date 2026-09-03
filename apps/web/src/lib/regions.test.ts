import { describe, expect, it } from "vitest";

import { countryName, flagEmoji } from "./regions";

/**
 * Framework-free country-picker helpers: an emoji flag built from two
 * regional-indicator code points (no network, no asset host) and a
 * localized country name via `Intl.DisplayNames`. Both degrade to the raw
 * code rather than throwing — an unmapped/malformed code must never crash
 * the region picker.
 */

describe("flagEmoji", () => {
  it("builds the two-codepoint regional-indicator flag for a valid code", () => {
    expect(flagEmoji("UZ")).toBe("🇺🇿");
  });

  it("is case-insensitive", () => {
    expect(flagEmoji("ru")).toBe(flagEmoji("RU"));
    expect(flagEmoji("ge")).toBe("🇬🇪");
  });

  it("falls back to the raw input for a code that isn't two letters", () => {
    expect(flagEmoji("USA")).toBe("USA");
    expect(flagEmoji("")).toBe("");
    expect(flagEmoji("1Z")).toBe("1Z");
  });
});

describe("countryName", () => {
  it("resolves a known code to a non-empty localized name", () => {
    const name = countryName("UZ", "ru");
    expect(name).not.toBe("");
    expect(name).not.toBe("UZ");
  });

  it("resolves the same code differently per locale", () => {
    expect(countryName("UZ", "ru")).not.toBe(countryName("UZ", "en"));
  });

  it("falls back to the upper-cased code for a malformed region subtag", () => {
    // Not two letters / three digits — `Intl.DisplayNames#of` throws a
    // `RangeError` for this, which the try/catch below must swallow.
    expect(countryName("nope", "ru")).toBe("NOPE");
  });
});
