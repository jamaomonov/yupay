import { describe, expect, it } from "vitest";

import { bodySchema, endpoints } from "./contract";
import { exampleOf } from "./example";

function orderBody(): Record<string, unknown> {
  const endpoint = endpoints().find((entry) => entry.id === "post-orders");
  if (endpoint === undefined) throw new Error("post-orders is missing from the contract");
  const body = exampleOf(bodySchema(endpoint.operation.requestBody?.content));
  if (typeof body !== "object" || body === null) throw new Error("the order body is not an object");
  return body as Record<string, unknown>;
}

/**
 * The sample on the one call that spends money.
 *
 * `quantity` and `amount_usd` sit side by side in `MerchantOrderCreateIn` and
 * are mutually exclusive per SKU kind, so the generator walking every property
 * produced a body that 422s for every `sku_id` a reader could substitute — on
 * the quickstart's step 4, right after they have proven their signature works.
 * The natural suspicion is then the signature, which is the one thing that is
 * fine.
 *
 * Pinned here rather than trusted to review: re-adding either field is a
 * one-character change to a `Set`, and the page still renders.
 */
describe("the create-order example body", () => {
  it("is a valid `fixed` order — neither quantity nor amount_usd", () => {
    const body = orderBody();
    expect(body).not.toHaveProperty("quantity");
    expect(body).not.toHaveProperty("amount_usd");
  });

  it("still carries the fields the call cannot work without", () => {
    const body = orderBody();
    expect(body["merchant_order_id"]).toBe("shop-10482");
    expect(body["sku_id"]).toEqual(expect.any(String));
  });

  it("names a real brand slug rather than the literal `brand`", () => {
    // `"brand": "brand"` is well-formed and a 404 the reader has no clue
    // about — the last-resort scalar, not an example.
    const brand = exampleOf({ type: "string" }, "brand");
    expect(brand).toBe("pubg-mobile");
  });
});
