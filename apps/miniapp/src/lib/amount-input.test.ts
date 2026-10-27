import { describe, expect, it } from "vitest";

import { cleanAmount, groupAmount } from "./amount-input";

describe("groupAmount", () => {
  it("groups soʻm by thousands", () => {
    expect(groupAmount("50000")).toBe("50 000");
    expect(groupAmount("1234567")).toBe("1 234 567");
    expect(groupAmount("999")).toBe("999");
    expect(groupAmount("")).toBe("");
  });

  it("leaves the fraction alone", () => {
    expect(groupAmount("12500.5")).toBe("12 500.5");
    expect(groupAmount("10.")).toBe("10.");
  });
});

describe("cleanAmount", () => {
  it("drops the grouping it put there and anything else typed", () => {
    expect(cleanAmount("50 000")).toBe("50000");
    expect(cleanAmount("1 234 abc")).toBe("1234");
  });

  it("keeps one decimal separator, a comma counting as one", () => {
    expect(cleanAmount("12,5")).toBe("12.5");
    expect(cleanAmount("1.2.3")).toBe("1.23");
  });
});
