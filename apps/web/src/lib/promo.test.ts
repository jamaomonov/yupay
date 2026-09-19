import { describe, expect, test } from "vitest";

import { ApiError } from "./client";
import { promoErrorKey } from "./promo";

/** A problem+json refusal the way `POST /promo/redeem` returns one — `code`
 *  sits at the body's top level (see `client.ts`'s `ApiError.code`). */
function conflict(code?: string): ApiError {
  return new ApiError(
    409,
    "/promo/redeem",
    "https://app.yupay.uz/errors/conflict",
    "promo code refused",
    undefined,
    code,
  );
}

describe("promoErrorKey", () => {
  test("tells the four refusal reasons apart", () => {
    // A bare 409 used to read "already used" for all of these, which lies to
    // a customer whose code merely expired or ran out.
    expect(promoErrorKey(conflict("already_redeemed"))).toBe("promoAlreadyUsed");
    expect(promoErrorKey(conflict("expired"))).toBe("promoExpired");
    expect(promoErrorKey(conflict("exhausted"))).toBe("promoExhausted");
    expect(promoErrorKey(conflict("inactive"))).toBe("promoInactive");
  });

  test("falls back to the blanket wording for a 409 with no code", () => {
    expect(promoErrorKey(conflict())).toBe("promoUsed");
  });

  test("falls back for an unrecognised code rather than leaking it", () => {
    expect(promoErrorKey(conflict("some_future_reason"))).toBe("promoUsed");
  });

  test("maps 404 to 'no such code'", () => {
    expect(
      promoErrorKey(new ApiError(404, "/promo/redeem", undefined, "promo code not found")),
    ).toBe("promoNotFound");
  });

  test("treats other statuses and non-API failures as our fault", () => {
    expect(promoErrorKey(new ApiError(500, "/promo/redeem"))).toBe("promoError");
    expect(promoErrorKey(new TypeError("network down"))).toBe("promoError");
    expect(promoErrorKey(null)).toBe("promoError");
  });
});
