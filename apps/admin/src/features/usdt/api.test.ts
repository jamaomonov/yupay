import { describe, expect, it } from "vitest";

import {
  explorerAddress,
  explorerTx,
  floorToCents,
  formatUsdt,
  parseUsdBound,
  shortHash,
} from "./api";

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
  it("floors an 18-decimal BEP20 amount", () => {
    expect(floorToCents("25.129999999999999999")).toBe("25.12");
  });
});

describe("formatUsdt", () => {
  it("trims trailing zeros to at least two decimals and groups thousands", () => {
    expect(formatUsdt("1234.500000")).toBe("1 234.50");
    expect(formatUsdt("10.123456")).toBe("10.123456");
    expect(formatUsdt("3")).toBe("3.00");
  });
  it("shows at most six decimals of an 18-decimal amount, cut not rounded", () => {
    expect(formatUsdt("1.123456789000000000")).toBe("1.123456");
    expect(formatUsdt("2.999999999999999999")).toBe("2.999999");
    expect(formatUsdt("5.100000000000000000")).toBe("5.10");
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

describe("explorer links", () => {
  const tx = "0xabc";
  const addr = "0xAbC";
  it("TRC20 goes to tronscan", () => {
    expect(explorerTx("trc20", "ff")).toBe("https://tronscan.org/#/transaction/ff");
    expect(explorerAddress("trc20", "TXa")).toBe("https://tronscan.org/#/address/TXa");
  });
  it("BEP20 goes to bscscan", () => {
    expect(explorerTx("bep20", tx)).toBe("https://bscscan.com/tx/0xabc");
    expect(explorerAddress("bep20", addr)).toBe("https://bscscan.com/address/0xAbC");
  });
  it("ERC20 goes to etherscan", () => {
    expect(explorerTx("erc20", tx)).toBe("https://etherscan.io/tx/0xabc");
    expect(explorerAddress("erc20", addr)).toBe("https://etherscan.io/address/0xAbC");
  });
});
