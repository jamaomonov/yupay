import { describe, expect, it } from "vitest";

import { formatMoment } from "./datetime";

const NOW = new Date(2026, 9, 20, 15, 0);

describe("formatMoment", () => {
  it("names today and yesterday", () => {
    expect(formatMoment(new Date(2026, 9, 20, 14, 27).toISOString(), "ru", NOW)).toBe(
      "Сегодня, 14:27",
    );
    expect(formatMoment(new Date(2026, 9, 19, 9, 5).toISOString(), "ru", NOW)).toBe("Вчера, 09:05");
  });

  it("drops this year and keeps another", () => {
    expect(formatMoment(new Date(2026, 9, 18, 14, 27).toISOString(), "ru", NOW)).toBe(
      "18 окт., 14:27",
    );
    expect(formatMoment(new Date(2025, 11, 31, 8, 0).toISOString(), "ru", NOW)).toMatch(/2025/);
  });

  it("speaks the reader's language", () => {
    expect(formatMoment(new Date(2026, 9, 20, 14, 27).toISOString(), "en", NOW)).toMatch(
      /^Today, /,
    );
  });
});
