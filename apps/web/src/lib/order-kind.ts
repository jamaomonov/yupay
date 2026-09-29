import type { OrderItemOut } from "@/lib/orders-types";

import { isSkinItem } from "@/lib/orders-types";

/** What an order delivered, for copy that must not call a code or a skin a top-up. */
export type DeliveredKind = "topUp" | "voucher" | "skin" | "mixed";

/**
 * A CS2 skin is seeded as a top-up but arrives as a Steam trade, so it is checked first;
 * then one kind across every line, else `mixed`. Mirrors the mini app's `orderKind`.
 */
export function deliveredKind(items: OrderItemOut[]): DeliveredKind {
  if (items.some(isSkinItem)) return "skin";
  const kinds = new Set(items.map((i) => i.display?.product_kind).filter(Boolean));
  if (kinds.size !== 1) return "mixed";
  return kinds.has("voucher") ? "voucher" : kinds.has("top_up") ? "topUp" : "mixed";
}
