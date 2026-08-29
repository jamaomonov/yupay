import { describe, expect, it } from "vitest";

import { cartSignature, rejectionKey } from "./PromoField";

import { translate } from "@/lib/i18n/core";

/**
 * This app has no React rendering harness — no jsdom, no testing-library — and
 * tests exported logic instead, the way `OrderSuccess.test.tsx` tests
 * `providerLabel`. So the mapping from a server rejection reason to the
 * sentence a buyer reads is tested here directly, and it is the part worth
 * testing: a wrong mapping means someone retypes a code that can never work.
 */

describe("rejectionKey", () => {
  it("gives every rejection its own message", () => {
    expect(rejectionKey("unknown")).toBe("topup.promoErrUnknown");
    expect(rejectionKey("already_used")).toBe("topup.promoErrAlreadyUsed");
    expect(rejectionKey("not_first_order")).toBe("topup.promoErrNotFirstOrder");
    expect(rejectionKey("own_code")).toBe("topup.promoErrOwnCode");
    expect(rejectionKey("pending_coded_order")).toBe("topup.promoErrPending");
  });

  it("falls back to the generic message for a reason it does not know", () => {
    // A reason the server learns before this component does must read as
    // "could not check", never as an empty box.
    expect(rejectionKey("some_future_reason")).toBe("topup.promoErrGeneric");
    expect(rejectionKey(undefined)).toBe("topup.promoErrGeneric");
    expect(rejectionKey("")).toBe("topup.promoErrGeneric");
  });

  it("maps only to keys that actually exist in the catalogue", () => {
    // A key with no message renders as the key itself — visible nonsense in
    // the middle of checkout. `translate` returns the key when it misses, so
    // any mapping that differs from its own name is a real message.
    for (const reason of [
      "unknown",
      "already_used",
      "not_first_order",
      "own_code",
      "pending_coded_order",
      "anything_else",
    ]) {
      expect(translate(rejectionKey(reason))).not.toBe(rejectionKey(reason));
    }
  });
});

describe("cartSignature", () => {
  it("is stable across the host rebuilding its array literal", () => {
    // The host builds `items` inline on every render. Keyed on the array
    // itself, the re-pricing effect would fire forever; keyed on this, it
    // fires when the cart actually changed.
    expect(cartSignature("UZS", [{ sku_id: "a", qty: 1 }])).toBe(
      cartSignature("UZS", [{ sku_id: "a", qty: 1 }]),
    );
  });

  it("changes when the package does", () => {
    expect(cartSignature("UZS", [{ sku_id: "a", qty: 1 }])).not.toBe(
      cartSignature("UZS", [{ sku_id: "b", qty: 1 }]),
    );
  });

  it("changes when a variable amount does", () => {
    // Telegram Stars and other variable SKUs re-price on the amount alone.
    expect(cartSignature("UZS", [{ sku_id: "a", qty: 1, amount_usd: "5.00" }])).not.toBe(
      cartSignature("UZS", [{ sku_id: "a", qty: 1, amount_usd: "9.00" }]),
    );
  });

  it("changes when the currency does", () => {
    expect(cartSignature("UZS", [{ sku_id: "a", qty: 1 }])).not.toBe(
      cartSignature("USD", [{ sku_id: "a", qty: 1 }]),
    );
  });
});
