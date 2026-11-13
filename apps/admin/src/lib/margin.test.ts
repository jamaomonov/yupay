import { describe, expect, it } from "vitest";

import { actualMarginNote } from "./margin";

describe("actualMarginNote", () => {
  it("flags a price parked above the target", () => {
    expect(actualMarginNote("10", "116.576", "144.22")).toBe("По факту 23,7% — цена выше цели.");
  });

  it("stays quiet on rounding", () => {
    expect(actualMarginNote("10", "116.576", "128.24")).toBeNull();
  });

  it("flags a price under the target", () => {
    expect(actualMarginNote("20", "10", "11")).toBe("По факту 10% — цена ниже цели.");
  });

  it("needs all three numbers", () => {
    expect(actualMarginNote("", "10", "12")).toBeNull();
    expect(actualMarginNote("20", "", "12")).toBeNull();
  });
});
