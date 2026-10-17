import { describe, expect, it } from "vitest";

import { fill, formatSum } from "./format";

describe("formatSum", () => {
  it("groups whole soʻm by thousands", () => {
    expect(formatSum("61264.000000")).toBe("61 264");
    expect(formatSum("1178020")).toBe("1 178 020");
    expect(formatSum(950)).toBe("950");
  });

  it("rounds to whole soʻm", () => {
    expect(formatSum("12059.6")).toBe("12 060");
  });

  it("shows a dash for a value that is not a number", () => {
    expect(formatSum("abc")).toBe("—");
  });
});

describe("fill", () => {
  it("replaces known placeholders and keeps unknown ones", () => {
    expect(fill("Версия {version} {x}", { version: "0.1.0" })).toBe("Версия 0.1.0 {x}");
  });
});
