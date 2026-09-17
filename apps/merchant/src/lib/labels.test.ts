import { describe, expect, it } from "vitest";

import { orderTitle } from "./labels";

describe("orderTitle", () => {
  it("names the product, not the id", () => {
    expect(
      orderTitle({ sku_code: "pubgm-660", sku_name: "660 UC", brand_name: "PUBG Mobile" }, "x"),
    ).toBe("PUBG Mobile · 660 UC");
  });
  it("falls back to the sku code, then to the caller's fallback", () => {
    expect(orderTitle({ sku_code: "pubgm-660" }, "x")).toBe("pubgm-660");
    expect(orderTitle({ sku_code: "" }, "Заказ")).toBe("Заказ");
  });
});
