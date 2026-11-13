import { describe, expect, it } from "vitest";

import { inputStyles } from "./input";

describe("inputStyles", () => {
  it("is the checkout field by default: 46px, visible border, card fill", () => {
    const c = inputStyles();
    expect(c).toContain("h-[46px]");
    expect(c).toContain("border-border-2");
    expect(c).toContain("bg-card");
    expect(c).toContain("px-3.5");
  });

  it("swaps the border for invalid, padding for an icon, height for a textarea", () => {
    expect(inputStyles({ invalid: true })).toContain("border-danger");
    expect(inputStyles({ icon: true })).toContain("pl-10");
    expect(inputStyles({ icon: true })).not.toContain("px-3.5");
    expect(inputStyles({ multiline: true })).not.toContain("h-[46px]");
  });
});
