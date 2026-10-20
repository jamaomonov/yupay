import { describe, expect, it } from "vitest";

import { usd } from "./EconomicsCard";

describe("usd", () => {
  it("shows cents, and a unit cost to four places without trailing zeros", () => {
    expect(usd("1.700000")).toBe("$1.70");
    expect(usd("-0.25")).toBe("−$0.25");
    expect(usd("0.8500", true)).toBe("$0.85");
    expect(usd("0.015576", true)).toBe("$0.0155");
  });
});
