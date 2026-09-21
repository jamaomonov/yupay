import type { SchemaNode } from "@/lib/contract";

import { isNullable, resolve } from "@/lib/contract";

/**
 * A plausible value for a schema, for the example bodies on the reference.
 *
 * Deterministic and derived from the contract, never hand-written: a
 * hand-written example is a second copy of the shape, and it is the copy that
 * goes stale the day a field is added. What it cannot derive — that a price
 * looks like "16.54" and not like "string" — comes from the field's own
 * format, pattern and name, in that order.
 */

/** Fixed, so the page is byte-identical between builds and diffs cleanly. */
const NOW = "2026-09-15T10:46:37Z";

const BY_NAME: Record<string, unknown> = {
  merchant_order_id: "shop-10482",
  order_id: "01a0a39a-59cc-7ec2-8d6f-73f2e43b0a46",
  transaction_id: "01a0a39a-5b0a-74c0-b954-ab38c7d25da0",
  sku_id: "01a042ce-7bf4-7880-83bc-d9688237c93b",
  brand_id: "01a042ce-a2ed-75a2-8975-53fdf0141865",
  product_id: "01a042ce-a2f1-7a10-9a5e-2f0c2b9d1f22",
  merchant_id: "01a0a399-fd8b-7432-83dc-fd3cc6f3d5f9",
  sku_code: "pubgm-660",
  slug: "pubg-mobile",
  // Without this, `brand` falls through to the last resort below and the
  // sample sends `"brand": "brand"` — well-formed, and a 404 the reader has
  // no clue about.
  brand: "pubg-mobile",
  name: "660 UC",
  title: "ACME Resale",
  status: "delivered",
  kind: "fixed",
  unit: "stars",
  player_id: "1313232551",
  server_id: "2001",
  key: "player_id",
  type: "text",
  pattern: "^[0-9]{6,12}$",
  event: "order.delivered",
  artifact_kind: "voucher_code",
  code: "invalid_request",
  detail: "quantity is required for a unit SKU",
  category_slug: "games",
  category_name: "Игры",
  logo_url: "https://cdn.yupay.uz/brands/pubg-mobile.png",
  hero_image_url: "https://cdn.yupay.uz/brands/pubg-mobile-hero.jpg",
  next_cursor: null,
  failure_reason: null,
};

const MONEY = new Set([
  "price_usd",
  "balance_usd",
  "amount_usd",
  "refunded_usd",
  "expected_price",
  "retail_price_usd",
  "min_amount_usd",
  "max_amount_usd",
]);

function scalar(name: string, node: SchemaNode): unknown {
  if (node.default !== undefined) return node.default;
  if (node.examples?.[0] !== undefined) return node.examples[0];
  if (node.const !== undefined) return node.const;
  if (node.enum?.[0] !== undefined) return node.enum[0];
  if (name in BY_NAME) return BY_NAME[name];
  if (MONEY.has(name)) return "16.54";
  if (name === "unit_price_usd") return "0.016537";
  if (node.format === "date-time") return NOW;
  const type = Array.isArray(node.type) ? node.type[0] : node.type;
  switch (type ?? "string") {
    case "integer":
      return name.endsWith("_qty") || name === "quantity" ? 1000 : 1;
    case "number":
      return 1;
    case "boolean":
      return true;
    case "null":
      return null;
    default:
      return name === "" ? "string" : name.replaceAll("_", " ");
  }
}

/**
 * Properties this generator must NOT emit together, and the one it keeps.
 *
 * `MerchantOrderCreateIn` declares `quantity` and `amount_usd` side by side,
 * but they are mutually exclusive AND mutually exhaustive per SKU kind
 * (`merchants/quote.py`): a fixed denomination refuses `quantity`
 * (`422 quantity_not_accepted`), a unit-priced or amount-priced SKU refuses
 * `amount_usd` (`422 amount_not_accepted`). There is no third case — so a
 * body carrying both, which is what walking every property produced, is
 * rejected for EVERY sku_id a reader could substitute.
 *
 * That body was the quickstart's step 4 and the reference's `post-orders`
 * sample: the one call that spends money, guaranteed to 422, right after the
 * reader has just proven their signature works. The natural first suspicion
 * is the signature, which is the one thing that is fine.
 *
 * Both are dropped rather than one being picked, because the remaining shape
 * is then exactly a `fixed` order — the most common kind, and correct as
 * pasted. Which field to add for the other two kinds is stated in prose on
 * the quickstart (`docs.kinds*`), where a rule belongs.
 */
const OMIT_FROM_EXAMPLES: ReadonlySet<string> = new Set(["quantity", "amount_usd"]);

/**
 * Build an example value for `node`.
 *
 * `depth` stops a self-referential model — none today, but a catalog that
 * grows a "related brands" field would be one — from recursing forever.
 */
export function exampleOf(node: SchemaNode | undefined, name = "", depth = 0): unknown {
  if (node === undefined || depth > 6) return null;
  const nullable = isNullable(node);
  if (node.anyOf !== undefined) {
    const branch = node.anyOf.find((entry) => entry.type !== "null");
    // A nullable field whose name says it is usually absent shows as `null`,
    // which is the more useful example: it is the case a client forgets.
    if (nullable && BY_NAME[name] === null) return null;
    return exampleOf(branch, name, depth);
  }
  if (node.allOf?.length === 1) return exampleOf(node.allOf[0], name, depth);

  const target = node.$ref === undefined ? node : resolve(node);
  if (target.type === "array") {
    return [exampleOf(target.items, name, depth + 1)];
  }
  if (target.properties !== undefined) {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(target.properties)) {
      if (OMIT_FROM_EXAMPLES.has(key)) continue;
      out[key] = exampleOf(child, key, depth + 1);
    }
    return out;
  }
  if (target.type === "object") return {};
  return scalar(name, target);
}

/** The example as a JSON string, ready for a `<pre>`. */
export function exampleJson(node: SchemaNode | undefined): string {
  return JSON.stringify(exampleOf(node), null, 2);
}
