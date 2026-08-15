/** Mirrors the backend's OrderAdminOut shape. */

export type OrderStatus =
  | "pending_payment"
  | "paid"
  | "fulfilling"
  | "fulfilled"
  | "delivered"
  | "failed"
  | "cancelled"
  | "expired"
  | "refunded"
  | "partially_refunded";

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
  total: number;
}

export const STATUS_LABEL: Record<OrderStatus, string> = {
  pending_payment: "Ждёт оплаты",
  paid: "Оплачен",
  fulfilling: "В работе",
  fulfilled: "Готов",
  delivered: "Доставлен",
  failed: "Проблемный",
  cancelled: "Отменён",
  expired: "Истёк",
  refunded: "Возврат",
  partially_refunded: "Частичный возврат",
};

export const STATUS_TONE: Record<OrderStatus, string> = {
  pending_payment: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  paid: "bg-[var(--info-soft)] text-[var(--info-fg)]",
  fulfilling: "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]",
  fulfilled: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  delivered: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  failed: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  cancelled: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  expired: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  refunded: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  partially_refunded: "bg-[var(--info-soft)] text-[var(--info-fg)]",
};
