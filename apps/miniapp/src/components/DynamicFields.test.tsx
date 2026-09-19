import { describe, expect, test } from "vitest";

import { pickLocalized, resolveHelpImages } from "./DynamicFields";

import type { HelpImage } from "@/lib/catalog";

/**
 * This app has no jsdom/testing-library (see PromoField.test.tsx) — the
 * component is thin glue over `resolveHelpImages`, so that pure function
 * carries the coverage: order, captions, the non-empty-alt fallback, and
 * that a longer-than-expected list is passed through untouched (the cap is
 * the backend's business, not this function's).
 */

describe("resolveHelpImages", () => {
  test("renders images in order with their localized captions", () => {
    const images: HelpImage[] = [
      { url: "https://cdn.yupay.uz/help/1.png", caption: { ru: "Откройте профиль" } },
      { url: "https://cdn.yupay.uz/help/2.png", caption: { ru: "ID под ником" } },
    ];
    const resolved = resolveHelpImages(images, "ru");
    expect(resolved.map((i) => i.url)).toEqual([
      "https://cdn.yupay.uz/help/1.png",
      "https://cdn.yupay.uz/help/2.png",
    ]);
    expect(resolved[0]?.caption).toBe("Откройте профиль");
    expect(resolved[1]?.caption).toBe("ID под ником");
    // The caption is also the alt — it is the obvious meaningful source.
    expect(resolved[0]?.alt).toBe("Откройте профиль");
  });

  test("falls back to a non-empty step alt when a caption is missing", () => {
    const images: HelpImage[] = [
      { url: "https://cdn.yupay.uz/help/1.png", caption: null },
      { url: "https://cdn.yupay.uz/help/2.png", caption: {} },
    ];
    const resolved = resolveHelpImages(images, "ru");
    expect(resolved[0]?.caption).toBeNull();
    expect(resolved[0]?.alt.length).toBeGreaterThan(0);
    expect(resolved[1]?.caption).toBeNull();
    expect(resolved[1]?.alt.length).toBeGreaterThan(0);
    // Describes the step and its position, not a filename or blank string.
    expect(resolved[0]?.alt).toContain("1");
    expect(resolved[0]?.alt).toContain("2");
  });

  test("localizes the caption per active locale, falling back like pickLocalized", () => {
    const images: HelpImage[] = [
      { url: "https://cdn.yupay.uz/help/1.png", caption: { ru: "Шаг", en: "Step" } },
    ];
    expect(resolveHelpImages(images, "en")[0]?.caption).toBe("Step");
    // uz has no translation on this fixture — pickLocalized falls back to the
    // first available value rather than an empty string.
    expect(resolveHelpImages(images, "uz")[0]?.caption).toBe("Шаг");
  });

  test("falls back past an explicitly empty caption for the active locale", () => {
    // HelpImagesEditor always writes all three locale keys (`caption: { ru:
    // "", en: "", uz: "" }`), so an untouched locale arrives as `""`, not a
    // missing key. A plain `??` chain doesn't fall back on that — a
    // Russian-only caption used to render as no caption at all on EN/UZ.
    const images: HelpImage[] = [
      {
        url: "https://cdn.yupay.uz/help/1.png",
        caption: { ru: "Откройте профиль", en: "", uz: "" },
      },
    ];
    expect(resolveHelpImages(images, "en")[0]?.caption).toBe("Откройте профиль");
    expect(resolveHelpImages(images, "uz")[0]?.caption).toBe("Откройте профиль");
  });

  test("returns an empty list for null, undefined, or empty input", () => {
    expect(resolveHelpImages(null, "ru")).toEqual([]);
    expect(resolveHelpImages(undefined, "ru")).toEqual([]);
    expect(resolveHelpImages([], "ru")).toEqual([]);
  });

  test("passes a longer-than-expected list through untouched", () => {
    // The cap is the backend's business — this function must not re-implement
    // it or silently drop entries.
    const images: HelpImage[] = Array.from({ length: 9 }, (_, i) => ({
      url: `https://cdn.yupay.uz/help/${String(i)}.png`,
      caption: null,
    }));
    expect(resolveHelpImages(images, "ru")).toHaveLength(9);
  });
});

describe("pickLocalized (regression: still used for help_text alongside images)", () => {
  test("a field with text and no images still resolves its text", () => {
    expect(pickLocalized({ ru: "Текст" }, "ru")).toBe("Текст");
    expect(resolveHelpImages(null, "ru")).toEqual([]);
  });
});
