import { describe, expect, test } from "vitest";

import { txKindLabelKey } from "./wallet";

describe("txKindLabelKey", () => {
  test("maps the promo redemption kind the backend actually posts (promo.redeem)", () => {
    // Regression: the map keyed on "promo.grant", which never matched
    // promo/service.py's `kind="promo.redeem"`, so history showed the raw key.
    expect(txKindLabelKey("promo.redeem")).toBe("wallet.tx.promo");
  });

  test("maps other known ledger kinds to their labels", () => {
    expect(txKindLabelKey("admin.adjust")).toBe("wallet.tx.adminAdjust");
    expect(txKindLabelKey("payment.refund")).toBe("wallet.tx.refund");
    expect(txKindLabelKey("order.payment")).toBe("wallet.tx.orderPayment");
    expect(txKindLabelKey("cashback.grant")).toBe("wallet.tx.cashback");
    expect(txKindLabelKey("topup")).toBe("wallet.tx.topup");
  });

  test("returns null for an unknown kind (caller shows the raw kind)", () => {
    expect(txKindLabelKey("something.else")).toBeNull();
  });
});
