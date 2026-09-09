/** Mirrors the backend's OrderAdminOut shape.
 *
 *  Strings live in `@yupay/i18n/locales/{ru,en,uz}/admin.json` (parity
 *  CI-gated); the admin SPA is Russian-only today, so this reads the `ru`
 *  catalog directly, same as `features/merchants` and `features/catalog/b2b`.
 */

import adminRu from "@yupay/i18n/locales/ru/admin.json";
import { assertNever } from "@yupay/utils";

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

/** Every value `orders.source` can hold — `ck_orders_source_known`, migration
 *  0073. `web` / `miniapp` / `bot` are client-declared (the `X-Yupay-Surface`
 *  header); `merchant_api` is set server-side when a reseller orders through
 *  `/merchant/v1`; `merchant_panel` is allowed by the CHECK and written by
 *  nothing until M4's cabinet ships. */
export type OrderSource = "web" | "miniapp" | "bot" | "merchant_api" | "merchant_panel" | "unknown";

/** Deliberately not a coloured badge: the surface is context, not a state, and
 *  colouring it would compete with the status column beside it. */
export const SOURCE_LABEL: Record<OrderSource, string> = adminRu.orders.source;

/** Labels for the three actor arms — see {@link orderActorOf}. */
const ACTOR = adminRu.orders.actor;

/** `OrderAdminOut.failure_reason` — the closed vocabulary `/merchant/v1`
 *  publishes (`merchants.order_status`), rendered here for the operator who
 *  has to explain it to the reseller reading the same word.
 *
 *  It is **additive on the wire**: the backend says "treat an unknown value as
 *  still in flight", so a value this union does not know must render as
 *  nothing rather than as a crash or a blank chip — which is what
 *  `failureReasonLabel` does. */
export type OrderFailureReason =
  | "order_failed"
  | "fulfillment_failed"
  | "fulfillment_failed_refunded"
  | "fulfillment_delayed";

export const FAILURE_REASON_LABEL: Record<OrderFailureReason, string> =
  adminRu.orders.failureReason;

/** Colour for the suffix, by what the operator has to do about it.
 *
 *  Danger is reserved for the one state that is **waiting on a person**;
 *  a delay is a warning (it clears itself once a supplier is topped up), and
 *  the two endings are muted because there is nothing left to do. */
export const FAILURE_REASON_TONE: Record<OrderFailureReason, string> = {
  order_failed: "text-[var(--text-secondary)]",
  fulfillment_failed: "text-[var(--danger-fg)]",
  fulfillment_failed_refunded: "text-[var(--text-secondary)]",
  fulfillment_delayed: "text-[var(--warning-fg)]",
};

/** The label for a reason, or `null` when there is nothing to say — including
 *  for a value added to the server's vocabulary after this build. */
export function failureReasonLabel(reason: string | null): string | null {
  if (reason === null) return null;
  return FAILURE_REASON_LABEL[reason as OrderFailureReason] ?? null;
}

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
  /** The reseller that placed this order through `/merchant/v1`, or `null` for
   *  a retail one — the third arm of `ck_orders_actor_exclusive`. */
  merchant_id: string | null;
  /** That reseller's title. An operator recognises a name; nobody recognises a
   *  uuid, which is all a merchant order used to leave behind. */
  merchant_title: string | null;
  /** What this order took from the merchant's USD deposit, off the ledger.
   *  `null` for every retail order — their money is at an acquirer — and for a
   *  merchant order with no charge posting, which is a damaged row and not a
   *  state. `NUMERIC(20, 6)` on the wire: `"1.070000"`. */
  deposit_charged_usd: string | null;
  /** What has come back on it, by any route: the drain's automatic refund and
   *  any settlement support booked against the order. `"0"` when nothing has,
   *  and never more than `deposit_charged_usd`. */
  deposit_returned_usd: string;
  /** Which surface placed the order. `unknown` for anything that did not say —
   *  including every order older than the column. */
  source: OrderSource;
  /** Why the order has stopped moving, or `null` if it has not. The same
   *  closed vocabulary `/merchant/v1` publishes, from the same function.
   *
   *  Typed open, like `OrderItemOut.fulfillment_state` beside it: the server's
   *  own contract for this field is "additive, and treat an unknown value as
   *  still in flight", so a build older than the API must render nothing
   *  rather than assert. `failureReasonLabel` is where that happens. */
  failure_reason: string | null;
  /** ``catalog`` sale or ``wallet_topup`` 1:1 deposit (ADR-0058). */
  purpose?: string;
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

/** Who an order belongs to — the three arms of `ck_orders_actor_exclusive`,
 *  plus the one the CHECK forbids.
 *
 *  A discriminated union rather than a chain of `??` fallbacks, because that
 *  chain is what shipped the bug this replaces: `{guest_email ?? "Гость"}`
 *  reads a merchant order — both retail arms null by construction — as an
 *  anonymous buyer. The CHECK says exactly one arm is set, so the display is a
 *  switch over the arms, and `assertNever` on the default is what makes a
 *  fourth arm a compile error instead of a silent «Гость».
 *
 *  `none` cannot occur: the CHECK counts the set arms and requires the sum to
 *  be 1. It is here so the union has a total function into it and the switch
 *  has something honest to render if the database is ever hand-edited. */
export type OrderActor =
  | { kind: "user"; userId: string }
  | { kind: "guest"; email: string }
  | { kind: "merchant"; merchantId: string; title: string | null }
  | { kind: "none" };

/** The actor columns any order-shaped DTO must carry to be attributable. */
export type OrderActorFields = Pick<
  OrderAdminOut,
  "user_id" | "guest_email" | "merchant_id" | "merchant_title"
>;

/** Which arm this order's actor is. The one place the columns are read. */
export function orderActorOf(order: OrderActorFields): OrderActor {
  if (order.user_id !== null) return { kind: "user", userId: order.user_id };
  if (order.guest_email !== null) return { kind: "guest", email: order.guest_email };
  if (order.merchant_id !== null) {
    return { kind: "merchant", merchantId: order.merchant_id, title: order.merchant_title };
  }
  return { kind: "none" };
}

/** The actor as one line of plain text, for slots that cannot take a node.
 *
 *  A merchant falls back to its id when the title is missing — which the
 *  `RESTRICT` foreign key makes unreachable — because "Мерчант —" would say
 *  less than the uuid this whole change exists to replace. */
export function orderActorText(actor: OrderActor): string {
  switch (actor.kind) {
    case "user":
      return `${ACTOR.user} ${actor.userId.slice(0, 8)}…`;
    case "guest":
      return actor.email;
    case "merchant":
      return `${ACTOR.merchant} ${actor.title ?? actor.merchantId}`;
    case "none":
      return ACTOR.none;
    default:
      return assertNever(actor);
  }
}
