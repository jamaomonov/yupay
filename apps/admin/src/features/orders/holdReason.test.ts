import { describe, expect, it } from "vitest";

import { holdReasonText } from "./holdReason";

describe("holdReasonText", () => {
  it("names a shared IP, not the amount", () => {
    const text = holdReasonText("identity_shared_across_buyers");
    expect(text).toMatch(/одного IP/);
    expect(text).not.toMatch(/порога/);
  });

  it("keeps the amount wording for the amount rule", () => {
    expect(holdReasonText("amount_at_or_above_threshold")).toMatch(/порога ручной проверки/);
  });

  it("shows an unknown code instead of guessing", () => {
    expect(holdReasonText("some_new_rule")).toBe("Причина: some_new_rule.");
    expect(holdReasonText("")).toBe("Причина не записана.");
  });
});
