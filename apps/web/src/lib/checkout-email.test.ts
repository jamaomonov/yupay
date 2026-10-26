// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { lastCheckoutEmail, rememberCheckoutEmail } from "./guest-orders";

describe("checkout email memory", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts empty and returns the last address a checkout used", () => {
    expect(lastCheckoutEmail()).toBe("");
    rememberCheckoutEmail("a@example.com");
    rememberCheckoutEmail("b@example.com");
    expect(lastCheckoutEmail()).toBe("b@example.com");
  });

  it("does not forget an address because the next checkout had none", () => {
    rememberCheckoutEmail("a@example.com");
    rememberCheckoutEmail("");
    expect(lastCheckoutEmail()).toBe("a@example.com");
  });
});
