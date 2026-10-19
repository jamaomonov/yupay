import { describe, expect, it } from "vitest";

import { supportProduct } from "./order-helpers";

import type { OrderOut } from "@/lib/orders";

function withItems(...display: (Record<string, unknown> | null)[]): Pick<OrderOut, "items"> {
  return { items: display.map((d) => ({ display: d })) } as unknown as Pick<OrderOut, "items">; // only display is read
}

describe("supportProduct", () => {
  it("names the brand and the denomination", () => {
    const o = withItems({
      brand_name: "PUBG Mobile",
      denomination: "60 UC",
      variable_amount: false,
    });
    expect(supportProduct(o)).toBe("PUBG Mobile, 60 UC");
  });

  it("drops the placeholder denomination of a variable amount", () => {
    const o = withItems({
      brand_name: "Steam",
      denomination: "Любая сумма",
      variable_amount: true,
    });
    expect(supportProduct(o)).toBe("Steam");
  });

  it("counts the other lines and gives up without display data", () => {
    const two = withItems(
      { brand_name: "PUBG Mobile", denomination: "60 UC", variable_amount: false },
      { brand_name: "PUBG Mobile", denomination: "325 UC", variable_amount: false },
    );
    expect(supportProduct(two)).toBe("PUBG Mobile, 60 UC +1");
    expect(supportProduct(withItems(null))).toBeNull();
  });
});
