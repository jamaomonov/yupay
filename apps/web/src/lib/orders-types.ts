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
  fx_snapshot_id: string | null;
  expires_at: string;
  created_at: string;
  paid_at: string | null;
  fulfilled_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  items: OrderItemOut[];
}

export interface OrderListOut {
  items: OrderOut[];
}
