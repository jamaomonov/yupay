import { describe, expect, it } from "vitest";

import { checkoutErrorMessage } from "./TopUp";

import { ApiError } from "@/lib/api";
import { translate } from "@/lib/i18n/core";

describe("checkoutErrorMessage", () => {
  it("shows the geo-veto line for a payment-unavailable-abroad refusal", () => {
    // ADR-0063 enforcement point B: the API refuses a foreign guest/fresh
    // account with a 422 whose RFC 7807 `type` ends in
    // `/payment-unavailable-abroad`.
    const err = new ApiError(422, "Unprocessable Entity", {
      type: "https://app.yupay.uz/errors/payment-unavailable-abroad",
      title: "Payment unavailable from this location",
      status: 422,
      detail: "payment from abroad requires a signed-in account with order history",
    });
    expect(checkoutErrorMessage(err)).toBe(translate("topup.errAbroad"));
  });

  it("falls back to the API's own detail for any other ApiError", () => {
    const err = new ApiError(400, "Bad Request", { detail: "sku is sold out" });
    expect(checkoutErrorMessage(err)).toBe("sku is sold out");
  });

  it("falls back to the generic retry line for a non-ApiError failure", () => {
    expect(checkoutErrorMessage(new TypeError("network down"))).toBe(translate("topup.tryAgain"));
  });
});
