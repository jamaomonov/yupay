import { describe, expect, test } from "vitest";

import { ApiError } from "./api";
import { promoErrorKey } from "./promo";

/** A problem+json refusal as the promo endpoint returns it. */
function conflict(code?: string) {
  return new ApiError(409, "Conflict", {
    type: "https://app.yupay.uz/errors/conflict",
    title: "Conflict",
    status: 409,
    detail: "promo code refused",
    ...(code === undefined ? {} : { code }),
  });
}

describe("promoErrorKey", () => {
  test("tells the four refusal reasons apart", () => {
    // A bare 409 used to read "уже использован" for all of these, which lies
    // to a customer whose code merely expired or ran out.
    expect(promoErrorKey(conflict("already_redeemed"))).toBe("wallet.promoAlreadyUsed");
    expect(promoErrorKey(conflict("expired"))).toBe("wallet.promoExpired");
    expect(promoErrorKey(conflict("exhausted"))).toBe("wallet.promoExhausted");
    expect(promoErrorKey(conflict("inactive"))).toBe("wallet.promoInactive");
  });

  test("falls back to the blanket wording for a 409 with no code", () => {
    expect(promoErrorKey(conflict())).toBe("wallet.promoUsed");
  });

  test("falls back for an unrecognised code rather than leaking it", () => {
    expect(promoErrorKey(conflict("some_future_reason"))).toBe("wallet.promoUsed");
  });

  test("maps 404 to 'no such code'", () => {
    expect(promoErrorKey(new ApiError(404, "Not Found", { detail: "promo code not found" }))).toBe(
      "wallet.promoNotFound",
    );
  });

  test("treats other statuses and non-API failures as our fault", () => {
    expect(promoErrorKey(new ApiError(500, "Server Error", {}))).toBe("wallet.promoError");
    expect(promoErrorKey(new TypeError("network down"))).toBe("wallet.promoError");
    expect(promoErrorKey(null)).toBe("wallet.promoError");
  });
});
