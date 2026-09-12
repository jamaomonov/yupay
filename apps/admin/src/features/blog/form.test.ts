import { describe, expect, it } from "vitest";

import {
  PIN_CAP,
  eventPhase,
  fromDatetimeLocal,
  otherPublishedPins,
  packFaqs,
  toDatetimeLocal,
} from "./form";

describe("packFaqs", () => {
  it("drops empty pairs and reindexes per locale", () => {
    expect(
      packFaqs([
        { locale: "ru", sort_order: 9, question: "Где ID?", answer: "В профиле." },
        { locale: "ru", sort_order: 1, question: "  ", answer: "" },
        { locale: "en", sort_order: 4, question: "Where is the ID?", answer: "Profile." },
      ]),
    ).toEqual([
      { locale: "ru", sort_order: 0, question: "Где ID?", answer: "В профиле." },
      { locale: "en", sort_order: 0, question: "Where is the ID?", answer: "Profile." },
    ]);
  });

  it("rejects a half-filled pair", () => {
    expect(
      packFaqs([{ locale: "ru", sort_order: 0, question: "Где ID?", answer: "" }]),
    ).toBe("incomplete");
  });
});

describe("eventPhase", () => {
  const start = "2026-09-12T10:00:00.000Z";
  const end = "2026-09-12T12:00:00.000Z";

  it("classifies the window", () => {
    expect(eventPhase(start, end, Date.parse("2026-09-12T09:00:00.000Z"))).toBe("upcoming");
    expect(eventPhase(start, end, Date.parse("2026-09-12T11:00:00.000Z"))).toBe("live");
    expect(eventPhase(start, end, Date.parse("2026-09-12T13:00:00.000Z"))).toBe("ended");
  });

  it("rejects a missing or inverted window", () => {
    expect(eventPhase("", end)).toBe("missing");
    expect(eventPhase(end, start)).toBe("invalid");
  });
});

describe("datetime-local", () => {
  it("round-trips a local wall clock through UTC", () => {
    const local = "2026-09-12T15:30";
    const iso = fromDatetimeLocal(local);
    expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(toDatetimeLocal(iso)).toBe(local);
  });

  it("treats empty as empty", () => {
    expect(fromDatetimeLocal("")).toBe("");
    expect(toDatetimeLocal("")).toBe("");
  });
});

describe("otherPublishedPins", () => {
  it("counts published pins on the brand and ignores this post", () => {
    const items = [
      { id: "a", primary_brand_id: "ml", pin_on_brand: true, status: "published" as const },
      { id: "b", primary_brand_id: "ml", pin_on_brand: true, status: "published" as const },
      { id: "c", primary_brand_id: "ml", pin_on_brand: true, status: "draft" as const },
      { id: "d", primary_brand_id: "steam", pin_on_brand: true, status: "published" as const },
    ];
    expect(otherPublishedPins(items, "ml", "a")).toBe(1);
    expect(otherPublishedPins(items, "ml", undefined)).toBe(PIN_CAP);
  });
});
