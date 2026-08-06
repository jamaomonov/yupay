import { describe, expect, it } from "vitest";

import { parseAdjustAmount } from "./parseAmount";

describe("parseAdjustAmount", () => {
  it("accepts a plain credit", () => {
    expect(parseAdjustAmount("5000")).toEqual({
      value: "5000",
      isDebit: false,
      absolute: "5000",
    });
  });

  it("treats a comma as the decimal separator (RU keyboard reflex)", () => {
    expect(parseAdjustAmount("1250,50")).toEqual({
      value: "1250.50",
      isDebit: false,
      absolute: "1250.50",
    });
  });

  it("strips thousands separators, including a pasted non-breaking space", () => {
    expect(parseAdjustAmount("12 920")).toMatchObject({ value: "12920" });
    expect(parseAdjustAmount("12 920")).toMatchObject({ value: "12920" });
  });

  it("flags a negative as a clawback so the UI can say so out loud", () => {
    const parsed = parseAdjustAmount("-1250.50");
    expect(parsed).toEqual({ value: "-1250.50", isDebit: true, absolute: "1250.50" });
  });

  it("rejects the inputs the old form forwarded verbatim", () => {
    expect(parseAdjustAmount("abc")).toBe("not_a_number");
    // Scientific notation is never a deliberate customer credit.
    expect(parseAdjustAmount("1e9")).toBe("not_a_number");
    expect(parseAdjustAmount("--5")).toBe("not_a_number");
    expect(parseAdjustAmount("5.5.5")).toBe("not_a_number");
    expect(parseAdjustAmount("  ")).toBe("empty");
  });

  it("rejects zero and absurd magnitudes", () => {
    expect(parseAdjustAmount("0")).toBe("zero");
    expect(parseAdjustAmount("0,00")).toBe("zero");
    expect(parseAdjustAmount("999999999999")).toBe("too_large");
  });

  it("keeps ledger precision at 6 decimals", () => {
    expect(parseAdjustAmount("1.123456")).toMatchObject({ value: "1.123456" });
    expect(parseAdjustAmount("1.1234567")).toBe("too_many_decimals");
  });
});
