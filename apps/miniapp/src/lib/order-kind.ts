/**
 * What an order delivered — for copy that must not call a code or a CS2 skin a top-up.
 * Used by the status card and the «delivered» dialog; mirrors the web's `lib/order-kind.ts`.
 */

import { isSkinItem } from "./skin-trade";

import type { OrderOut, ProductKind } from "./orders";

export type OrderKind = "top_up" | "voucher" | "mixed" | "skin";

export function orderKind(order: Pick<OrderOut, "items">): OrderKind {
  // A CS2 skin is seeded as a top-up (its form matches that shape) but is
  // delivered as a Steam trade and refunded to the balance — its own copy.
  if (order.items.some(isSkinItem)) return "skin";
  const kinds = new Set(
    order.items.map((i) => i.display?.product_kind).filter((k): k is ProductKind => Boolean(k)),
  );
  if (kinds.size === 1) {
    return kinds.has("top_up") ? "top_up" : "voucher";
  }
  return "mixed";
}

const DELIVERED = {
  top_up: "topUp",
  voucher: "voucher",
  skin: "skin",
  mixed: "mixed",
} as const satisfies Record<OrderKind, string>;

/** The «delivered» dialog's title and body keys for this order. */
export function deliveredCopy(order: Pick<OrderOut, "items">) {
  const k = DELIVERED[orderKind(order)];
  return {
    title: `orderResult.delivered.${k}.title`,
    body: `orderResult.delivered.${k}.body`,
  } as const;
}

interface ShareCopy {
  key:
    | "success.shareStoryText"
    | "success.shareStoryTextGeneric"
    | "success.shareStoryTextBought"
    | "success.shareStoryTextBoughtGeneric"
    | "success.shareStoryTextSkin";
  params: Record<string, string>;
}

/** The story-share line: «пополнил» only for a top-up; a code is «купил», a skin its own. */
export function shareStoryCopy(
  order: Pick<OrderOut, "items">,
  brandName: string | null,
): ShareCopy {
  const kind = orderKind(order);
  if (kind === "skin") return { key: "success.shareStoryTextSkin", params: {} };
  const game = brandName ? { game: brandName } : null;
  if (kind === "top_up") {
    return game
      ? { key: "success.shareStoryText", params: game }
      : { key: "success.shareStoryTextGeneric", params: {} };
  }
  return game
    ? { key: "success.shareStoryTextBought", params: game }
    : { key: "success.shareStoryTextBoughtGeneric", params: {} };
}
