import type { OrderOut } from "@/lib/orders-types";

/** Tailwind classes per order status — background + text for the status chip.
 *  Shared between the logged-in and guest order-history cards. */
export const STATUS_CLS: Record<string, string> = {
  pending_payment: "bg-amber-500/15 text-amber-400",
  paid: "bg-emerald-500/15 text-emerald-400",
  fulfilling: "bg-sky-500/15 text-sky-400",
  fulfilled: "bg-emerald-500/15 text-emerald-400",
  delivered: "bg-emerald-500/15 text-emerald-400",
  failed: "bg-red-500/15 text-red-400",
  cancelled: "bg-tx-dim/15 text-tx-dim",
  expired: "bg-tx-dim/15 text-tx-dim",
  refunded: "bg-tx-dim/15 text-tx-dim",
  partially_refunded: "bg-tx-dim/15 text-tx-dim",
};

/** "Brand · Denomination (+N)" title for an order card, falling back to a
 *  generic "Order #id" when the first item carries no catalog display data
 *  (deleted SKU, etc). */
export function orderTitle(o: OrderOut, fallback: string): string {
  const d = o.items[0]?.display;
  if (!d) return fallback;
  const name = d.brand_name || d.product_name;
  const denom = d.denomination ? ` · ${d.denomination}` : "";
  const extra = o.items.length > 1 ? ` +${String(o.items.length - 1)}` : "";
  return `${name}${denom}${extra}`;
}

/** True when every item in the order is a top-up product (mirrors the Mini
 *  App's order-kind check and `StatusBlock`'s `isTopUp`) — a delivered
 *  top-up order shows "Credited" instead of "Delivered". */
export function isTopUpOrder(o: OrderOut): boolean {
  return o.items.length > 0 && o.items.every((i) => i.display?.product_kind === "top_up");
}

/** Muted subtitle for an order card: the product name when it differs from
 *  the brand name (already shown in the title), else the region — skipping
 *  the generic "GLOBAL" — else null when neither adds information. */
export function orderSubtitle(o: OrderOut): string | null {
  const d = o.items[0]?.display;
  if (!d) return null;
  if (d.product_name && d.product_name !== d.brand_name) return d.product_name;
  if (d.region && d.region !== "GLOBAL") return d.region;
  return null;
}
