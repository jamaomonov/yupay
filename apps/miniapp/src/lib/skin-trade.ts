/**
 * What the order page says about a CS2 skin line's Steam trade — the pure
 * half of `components/order/SkinTradeCard.tsx`, mirroring the web's card.
 * A refund to the balance is promised only where the API made one (the
 * customer declined, or every offer was sold); anything else is support's.
 */

import type { OrderItemOut, SkinTradeOut } from "./orders";

export type SkinTradeView =
  | { kind: "buying" }
  | { kind: "offer"; offerUrl: string | null; seller: string | null; acceptBy: string | null }
  | { kind: "received"; protectedUntil: string | null }
  | { kind: "refunded" }
  | { kind: "support" };

export function skinTradeView(trade: SkinTradeOut): SkinTradeView {
  switch (trade.state) {
    case "buying":
      return { kind: "buying" };
    case "offer_sent":
      return {
        kind: "offer",
        offerUrl: trade.offer_url,
        seller: trade.seller?.name ?? null,
        acceptBy: trade.send_until,
      };
    case "accepted":
      return { kind: "received", protectedUntil: trade.release_date };
    case "released":
      return { kind: "received", protectedUntil: null };
    case "failed":
      return trade.reason_code === "not_accepted" || trade.reason_code === "sold_out"
        ? { kind: "refunded" }
        : { kind: "support" };
    default: {
      const never: never = trade.state;
      return never;
    }
  }
}

/** The CS2 skin SKU (`scripts/seed/2026-09-29_cs2_skin_sku.py`). */
export const CS2_SKIN_SKU_CODE = "cs2-skin";

/**
 * A skin line, known by its SKU before the worker has written its trade row:
 * until then the order must not read as a top-up ("credited", "back to the card").
 */
export function isSkinItem(item: Pick<OrderItemOut, "skin_trade" | "display">): boolean {
  return Boolean(item.skin_trade) || item.display?.sku_code === CS2_SKIN_SKU_CODE;
}

/** The trade card's state before the worker has written the row. */
export const SKIN_TRADE_PENDING: SkinTradeOut = {
  state: "buying",
  offer_url: null,
  send_until: null,
  release_date: null,
  seller: null,
  reason_code: null,
};
