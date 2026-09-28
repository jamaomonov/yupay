export interface OrderItemDisplay {
  brand_slug: string;
  brand_name: string;
  product_slug: string;
  product_name: string;
  product_kind: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  image_url: string | null;
  variable_amount: boolean;
}

export interface OrderItemOut {
  id: string;
  sku_id: string;
  qty: number;
  unit_price_usd: string;
  fulfillment_state: string;
  fulfillment_data: Record<string, unknown>;
  display: OrderItemDisplay | null;
  /** A CS2 skin line's Steam trade as the buyer sees it (`skins.trade_view`). */
  skin_trade?: SkinTradeOut | null;
}

export type SkinTradeState = "buying" | "offer_sent" | "accepted" | "released" | "failed";
export type SkinTradeReason = "not_accepted" | "sold_out" | "support" | "other";

export interface SkinSellerOut {
  name: string | null;
  avatar_url: string | null;
  level: number | null;
  joined_at: string | null;
}

export interface SkinTradeOut {
  state: SkinTradeState;
  offer_url: string | null;
  send_until: string | null;
  release_date: string | null;
  seller: SkinSellerOut | null;
  reason_code: SkinTradeReason | null;
}

export interface OrderOut {
  id: string;
  status: string;
  currency: string;
  total_usd: string;
  total_charged: string;
  payment_provider: string | null;
  fx_snapshot_id: string | null;
  expires_at: string;
  created_at: string;
  paid_at: string | null;
  fulfilled_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  items: OrderItemOut[];
  /** `catalog` (a sale) or `wallet_topup` (a 1:1 balance deposit, Mini App only). */
  purpose?: string;
}

export interface OrderListOut {
  items: OrderOut[];
}

/**
 * A payment as `GET /api/v1/payments/by-order/{order_id}` returns it —
 * mirrors the API's `PaymentOut` (`apps/api/src/yupay/modules/payments/
 * schemas.py`), minus the timestamps the storefront has no use for. `status`
 * is the API's `PaymentStatus` literal (pending / requires_action / succeeded
 * / failed / cancelled / refunded / partially_refunded), kept as a plain
 * `string` here so an unknown value from a newer API degrades to "not
 * payable" rather than a type error.
 */
export interface PaymentOut {
  id: string;
  order_id: string;
  provider: string;
  status: string;
  amount: string;
  currency: string;
  intent_url: string | null;
  external_id: string | null;
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
