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
