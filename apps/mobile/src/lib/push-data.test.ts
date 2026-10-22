import { describe, expect, it } from "vitest";

import { orderOf } from "./push-data";

describe("orderOf", () => {
  it("reads the order a push points at", () => {
    expect(orderOf({ type: "order", order_id: "01a1" })).toBe("01a1");
  });

  it("ignores anything else", () => {
    expect(orderOf({ type: "promo", order_id: "01a1" })).toBeNull();
    expect(orderOf({ type: "order", order_id: 5 })).toBeNull();
    expect(orderOf(null)).toBeNull();
    expect(orderOf("order")).toBeNull();
  });
});
