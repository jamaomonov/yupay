import { describe, expect, it } from "vitest";

import { floorToCents, formatUsdt, parseUsdBound, shortHash } from "./api";

describe("floorToCents", () => {
  it("rounds down, never up", () => {
    expect(floorToCents("12.349999")).toBe("12.34");
    expect(floorToCents("100.010000")).toBe("100.01");
  });
  it("pads short fractions and whole numbers", () => {
    expect(floorToCents("5")).toBe("5.00");
    expect(floorToCents("5.1")).toBe("5.10");
  });
  it("keeps a sub-cent amount at zero and strips leading zeros", () => {
    expect(floorToCents("0.009999")).toBe("0.00");
    expect(floorToCents("007.50")).toBe("7.50");
  });
});

describe("formatUsdt", () => {
  it("trims trailing zeros to at least two decimals and groups thousands", () => {
    expect(formatUsdt("1234.500000")).toBe("1 234.50");
    expect(formatUsdt("10.123456")).toBe("10.123456");
    expect(formatUsdt("3")).toBe("3.00");
  });
});

describe("shortHash", () => {
  it("shortens long values with an ellipsis", () => {
    expect(shortHash("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")).toBe("TR7NHq…Lj6t");
  });
  it("leaves short values alone", () => {
    expect(shortHash("abcdef")).toBe("abcdef");
  });
});

describe("parseUsdBound", () => {
  it("accepts positive cents amounts, comma included", () => {
    expect(parseUsdBound("10")).toBe("10");
    expect(parseUsdBound("10,5")).toBe("10.5");
  });
  it("rejects zero, too many decimals and junk", () => {
    expect(parseUsdBound("0")).toBeNull();
    expect(parseUsdBound("1.234")).toBeNull();
    expect(parseUsdBound("abc")).toBeNull();
  });
});
