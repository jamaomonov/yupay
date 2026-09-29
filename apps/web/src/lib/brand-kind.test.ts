import { describe, expect, it } from "vitest";

import { isVoucherBrand } from "./brand-kind";

describe("isVoucherBrand", () => {
  it("is a brand that sells only codes", () => {
    expect(isVoucherBrand({ products: [{ kind: "voucher" }, { kind: "voucher" }] })).toBe(true);
    expect(isVoucherBrand({ products: [{ kind: "voucher" }, { kind: "top_up" }] })).toBe(false);
    expect(isVoucherBrand({ products: [{ kind: "top_up" }] })).toBe(false);
    // No products known (an older API): keep the top-up copy it always had.
    expect(isVoucherBrand({ products: [] })).toBe(false);
    expect(isVoucherBrand({})).toBe(false);
  });
});
