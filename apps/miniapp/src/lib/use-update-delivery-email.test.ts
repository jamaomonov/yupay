import { describe, expect, it } from "vitest";

import { deliveryEmailPatch } from "./use-update-delivery-email";

/**
 * A mini app account is a Telegram account with no email, so an order's codes
 * had nowhere to be sent. The settings screen is where the customer says where
 * — and the field it writes must never be the login identity.
 */
describe("deliveryEmailPatch", () => {
  it("writes delivery_email and never the login email", () => {
    const body = deliveryEmailPatch("me@example.com");
    expect(body).toEqual({ delivery_email: "me@example.com" });
    // `users.email` is uniquely indexed and three auth lookups resolve an
    // account by it. A settings screen writing an unverified address there
    // collides with a real account, or claims one a reset later targets.
    expect(body).not.toHaveProperty("email");
  });

  it("keeps an empty string, because that is how the address is cleared", () => {
    // Dropping it would make "clear my address" silently do nothing, and the
    // customer would go on believing they had removed it.
    expect(deliveryEmailPatch("")).toEqual({ delivery_email: "" });
    expect(deliveryEmailPatch("   ")).toEqual({ delivery_email: "" });
  });

  it("trims what a phone keyboard adds", () => {
    expect(deliveryEmailPatch("  me@example.com ")).toEqual({ delivery_email: "me@example.com" });
  });
});
