import { describe, expect, it } from "vitest";

import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("formats USD with en-US locale", () => {
    expect(formatMoney("12.34", "USD", "en-US")).toMatch(/12\.34/);
  });

  it("falls back gracefully for unknown currency", () => {
    expect(formatMoney("1", "XYZ", "en-US")).toContain("XYZ");
  });
});
