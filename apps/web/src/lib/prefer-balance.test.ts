import { expect, it } from "vitest";

import { preferBalance } from "./prefer-balance";

const base = { picked: false, fallback: "payme" };

it("selects the balance when it covers the order and the buyer has not chosen", () => {
  expect(preferBalance("payme", { ...base, ready: true })).toBe("wallet");
});

it("goes back to the default when the auto-picked balance stops covering", () => {
  expect(preferBalance("wallet", { ...base, ready: false })).toBe("payme");
});

it("leaves a card alone while the balance cannot pay", () => {
  expect(preferBalance("click", { ...base, ready: false })).toBe("click");
});

it("never overrides what the buyer picked by hand", () => {
  expect(preferBalance("click", { ...base, ready: true, picked: true })).toBe("click");
  expect(preferBalance("wallet", { ...base, ready: false, picked: true })).toBe("wallet");
});
