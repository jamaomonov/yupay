/**
 * A typed amount instead of a tile: dollars for the Steam wallet (`variable_amount`), a count
 * of units for Telegram Stars (`amount_unit` with `min_qty`/`max_qty`). Plain TS, unit-tested.
 * The same rules as the storefronts' `variable-amount.ts` and the API's `unit_sku.py`.
 */
import type { SkuOut } from "@yupay/api-client/types";

export type SkuKind = "fixed" | "usd" | "units";

export function skuKind(sku: SkuOut): SkuKind {
  if (sku.variable_amount === true) return "usd";
  if (sku.amount_unit != null && sku.min_qty != null && sku.max_qty != null) return "units";
  return "fixed";
}

/** What the buyer may type, and what one of it costs in soʻm (`display_price`). */
export interface AmountRule {
  kind: "usd" | "units";
  min: number;
  max: number;
  /** Soʻm per dollar (Steam) or per unit (Stars). */
  rate: number;
  /** «$» or «Stars», as the SKU names it. */
  unit: string;
  /** What the empty field suggests. */
  placeholder: number;
}

export function amountRule(sku: SkuOut): AmountRule | null {
  const kind = skuKind(sku);
  const rate = Number(sku.display_price?.amount);
  if (kind === "fixed" || !Number.isFinite(rate) || rate <= 0) return null;
  if (kind === "usd") {
    // Whole dollars, rounded inward: the field never offers what the API refuses.
    const min = Math.ceil(Number(sku.min_amount_usd ?? "1"));
    const max = Math.floor(Number(sku.max_amount_usd ?? "500"));
    return { kind, min, max, rate, unit: "$", placeholder: Math.max(min, 10) };
  }
  const min = sku.min_qty ?? 1;
  const max = sku.max_qty ?? min;
  return {
    kind,
    min,
    max,
    rate,
    unit: sku.amount_unit ?? "",
    placeholder: min,
  };
}

/** Whole numbers only: "1 000" reads as 1000, anything else as nothing typed yet. */
export function parseCount(text: string): number {
  const digits = text.replace(/\D/g, "").slice(0, 6);
  return digits === "" ? 0 : Number(digits);
}

export type CountCheck = "empty" | "low" | "high" | "ok";

export function checkCount(value: number, rule: AmountRule): CountCheck {
  if (value === 0) return "empty";
  if (value < rule.min) return "low";
  if (value > rule.max) return "high";
  return "ok";
}

/** The price in whole soʻm, rounded the way the API rounds a total (`_round_to_payable`). */
export function priceOf(value: number, rule: AmountRule): number {
  return Math.round(value * rule.rate);
}

/** How the line reads: «$25», «500 Stars» — dollars as the storefront and the order list write them. */
export function countLabel(value: number, rule: AmountRule): string {
  const grouped = value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return rule.kind === "usd" ? `$${grouped}` : `${grouped} ${rule.unit}`;
}

/** The order line's shape for a typed amount: dollars go as `amount_usd`, units as `qty`. */
export function lineOf(value: number, rule: AmountRule): { qty: number; amountUsd?: string } {
  return rule.kind === "usd" ? { qty: 1, amountUsd: value.toFixed(2) } : { qty: value };
}
