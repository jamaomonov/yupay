/** Mirrors the backend's OrderAdminOut shape. */

export type OrderStatus =
  | "pending_payment"
  | "paid"
  | "fulfilling"
  | "fulfilled"
  | "delivered"
  | "cancelled"
  | "expired"
  | "refunded";

export interface OrderItemDisplay {
  brand_slug: string;
  brand_name: string;
  product_slug: string;
  product_name: string;
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
  supplier_order_id: string | null;
  display: OrderItemDisplay | null;
}

export interface OrderEventOut {
  kind: string;
  payload: Record<string, unknown>;
  actor: string | null;
  created_at: string;
}

export interface OrderAdminOut {
  id: string;
  status: OrderStatus;
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
  user_id: string | null;
  guest_email: string | null;
  events: OrderEventOut[];
}

export interface OrderAdminListOut {
  items: OrderAdminOut[];
}

export const STATUS_LABEL: Record<OrderStatus, string> = {
  pending_payment: "Ждёт оплаты",
  paid: "Оплачен",
  fulfilling: "В работе",
  fulfilled: "Готов",
  delivered: "Доставлен",
  cancelled: "Отменён",
  expired: "Истёк",
  refunded: "Возврат",
};

export const STATUS_TONE: Record<OrderStatus, string> = {
  pending_payment: "bg-amber-100 text-amber-700",
  paid: "bg-sky-100 text-sky-700",
  fulfilling: "bg-violet-100 text-violet-700",
  fulfilled: "bg-emerald-100 text-emerald-700",
  delivered: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-zinc-100 text-zinc-600",
  expired: "bg-zinc-100 text-zinc-600",
  refunded: "bg-rose-100 text-rose-700",
};
