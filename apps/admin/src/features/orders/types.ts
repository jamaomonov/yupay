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

export type OrderSource = "web" | "miniapp" | "bot" | "unknown";

/** Deliberately not a coloured badge: the surface is context, not a state, and
 *  colouring it would compete with the status column beside it. */
export const SOURCE_LABEL: Record<OrderSource, string> = {
  web: "Сайт",
  miniapp: "Mini App",
  bot: "Бот",
  unknown: "—",
};

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
  /** Face value of the goods in USD. On a variable-amount (Steam) line this is
   *  the credit the buyer chose, NOT what they paid — use `charged_usd` for
   *  money. See `orders/revenue.py`. */
  total_usd: string;
  /** What the order is actually worth in USD, markup included. `null` only
   *  when a line's SKU could not be resolved. */
  charged_usd: string | null;
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
  /** Which surface placed the order. `unknown` for anything that did not say —
   *  including every order older than the column. */
  source: OrderSource;
  events: OrderEventOut[];
}

export interface OrderAdminListOut {
  items: OrderAdminOut[];
  total: number;
}

/** The request context an order was placed from — see ADR-0044. Mirrors
 *  `OrderEvidenceOut`. `null` on the pack for orders placed before the
 *  capture existed, or when the capture failed (it is best-effort by
 *  design: it must never be the reason a sale is lost). */
export interface OrderEvidenceOut {
  order_id: string;
  ip: string | null;
  user_agent: string | null;
  accept_language: string | null;
  /** Browser-reported timezone / locale / screen. Corroboration, not proof. */
  client_hints: Record<string, unknown>;
  created_at: string;
  /** When retention deletes this row. */
  purge_after: string;
}

/** `GET /api/v1/admin/orders/{id}/evidence` — what gets handed to an acquirer
 *  when a payment is disputed. Fetching it is audited server-side. */
export interface EvidencePackOut {
  order_id: string;
  status: string;
  total_charged: string;
  currency: string;
  created_at: string;
  paid_at: string | null;
  delivered_at: string | null;
  capture: OrderEvidenceOut | null;
  timeline: OrderEventOut[];
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
