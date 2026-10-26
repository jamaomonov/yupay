import { describe, expect, it } from "vitest";

import { change, moneyChange, presetWindow, rangeWindow, statsQuery, successShare } from "./stats";

describe("presetWindow", () => {
  const now = new Date("2026-10-26T12:00:00Z");

  it("ends every preset now and opens all time", () => {
    expect(presetWindow("24h", now).since?.toISOString()).toBe("2026-10-25T12:00:00.000Z");
    expect(presetWindow("7d", now).since?.toISOString()).toBe("2026-10-19T12:00:00.000Z");
    expect(presetWindow("all", now)).toEqual({ since: null, until: null });
  });
});

describe("rangeWindow", () => {
  it("covers whole local days, the last one included", () => {
    const window = rangeWindow("2026-10-01", "2026-10-03");
    expect(window?.since).toEqual(new Date(2026, 9, 1));
    expect(window?.until).toEqual(new Date(2026, 9, 4));
  });

  it("refuses an empty or inverted range", () => {
    expect(rangeWindow("", "2026-10-03")).toBeNull();
    expect(rangeWindow("2026-10-05", "2026-10-03")).toBeNull();
  });
});

describe("statsQuery", () => {
  it("sends the zone always and the bounds only when set", () => {
    expect(statsQuery({ since: null, until: null }, "Asia/Tashkent")).toBe(
      "/stats?tz=Asia%2FTashkent",
    );
    const q = statsQuery({ since: new Date("2026-10-01T00:00:00Z"), until: null }, "UTC");
    expect(q).toBe("/stats?tz=UTC&since=2026-10-01T00%3A00%3A00.000Z");
  });
});

describe("change", () => {
  it("is a rounded percentage, and nothing against zero", () => {
    expect(change(15, 10)).toBe(50);
    expect(change(5, 10)).toBe(-50);
    expect(change(5, 0)).toBeNull();
    expect(change(5, null)).toBeNull();
    expect(moneyChange("33.08", "16.54")).toBe(100);
  });
});

describe("successShare", () => {
  it("counts only finished orders", () => {
    expect(successShare(9, 1)).toBe(90);
    expect(successShare(0, 0)).toBeNull();
  });
});
