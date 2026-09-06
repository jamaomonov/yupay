/**
 * One shared localized status/event renderer.
 *
 * Round-1 built localized + colored maps for order status
 * (`features/orders/types.ts`) and payment status (`features/payments/types.ts`),
 * but every other status/event-ish value in the admin SPA still leaked raw
 * English straight from the backend: order-timeline event kinds
 * (`order.paid`, `payment.succeeded`, …), per-item `fulfillment_state`,
 * `FulfillmentTask.status`, wallet `Transaction.kind` (`payment.refund`,
 * `wallet_payment`, `admin.adjust`), and the review moderation status.
 *
 * This module is the single place new "domains" get registered, and
 * `<StatusChip>` is the one component every status/event badge in the admin
 * SPA should render through — reusing the *existing* order/payment maps
 * (never duplicating them) and adding the missing domains alongside.
 */

import { Badge } from "./Badge";

import { STATUS_LABEL as ORDER_LABEL, STATUS_TONE as ORDER_TONE } from "@/features/orders/types";
import {
  STATUS_LABEL as PAYMENT_LABEL,
  STATUS_TONE as PAYMENT_TONE,
} from "@/features/payments/types";

export interface StatusMeta {
  label: string;
  tone: string;
}

const MUTED = "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
const SUCCESS = "bg-[var(--success-soft)] text-[var(--success-fg)]";
const DANGER = "bg-[var(--danger-soft)] text-[var(--danger-fg)]";
const WARNING = "bg-[var(--warning-soft)] text-[var(--warning-fg)]";
const INFO = "bg-[var(--info-soft)] text-[var(--info-fg)]";
const ACCENT = "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]";

function fromLabelTone<K extends string>(
  labels: Record<K, string>,
  tones: Record<K, string>,
): Record<string, StatusMeta> {
  const out: Record<string, StatusMeta> = {};
  for (const k of Object.keys(labels) as K[]) {
    out[k] = { label: labels[k], tone: tones[k] };
  }
  return out;
}

/** ``OrderEventOut.kind`` — order timeline + audit feed. Covers every kind
 *  actually emitted by ``orders``/``payments``/``fulfillment`` services. */
const EVENT_KIND: Record<string, StatusMeta> = {
  "order.created": { label: "Заказ создан", tone: MUTED },
  "order.paid": { label: "Оплачен", tone: INFO },
  "order.held_for_review": { label: "На проверке", tone: WARNING },
  "order.fulfilling": { label: "Выдаётся", tone: ACCENT },
  "order.delivered": { label: "Доставлен", tone: SUCCESS },
  "order.failed": { label: "Отмечен проблемным", tone: DANGER },
  "order.cancelled": { label: "Отменён", tone: MUTED },
  "order.expired": { label: "Истёк", tone: MUTED },
  // Audited admin reads of customer data — a bearer code and a personal
  // address respectively. Both are answers to "who looked at this".
  "admin.deliveries_viewed": { label: "Админ смотрел выдачу", tone: MUTED },
  "admin.evidence_viewed": { label: "Админ смотрел контекст", tone: MUTED },
  "payments.cascaded_cancel": { label: "Платежи отменены каскадом", tone: MUTED },
  "payment.pending": { label: "Платёж: ожидание", tone: MUTED },
  "payment.requires_action": { label: "Платёж: нужно действие", tone: WARNING },
  "payment.succeeded": { label: "Платёж: успешно", tone: SUCCESS },
  "payment.failed": { label: "Платёж: ошибка", tone: DANGER },
  "payment.cancelled": { label: "Платёж: отменён", tone: MUTED },
  "payment.refund": { label: "Платёж: возврат оформлен", tone: INFO },
  "payment.refunded": { label: "Платёж: возврат", tone: INFO },
  "payment.partially_refunded": { label: "Платёж: частичный возврат", tone: INFO },
};

/** Per-order-item ``fulfillment_state`` (``ck_order_items_state``). */
const FULFILLMENT_STATE: Record<string, StatusMeta> = {
  pending: { label: "Ожидание", tone: MUTED },
  reserved: { label: "Резерв", tone: WARNING },
  in_progress: { label: "В процессе", tone: ACCENT },
  delivered: { label: "Выдан", tone: SUCCESS },
  failed: { label: "Ошибка", tone: DANGER },
  refunded: { label: "Возврат", tone: INFO },
};

/** ``FulfillmentTask.status``. */
const TASK_STATUS: Record<string, StatusMeta> = {
  pending: { label: "Ожидание", tone: MUTED },
  in_progress: { label: "В процессе", tone: ACCENT },
  succeeded: { label: "Успешно", tone: SUCCESS },
  failed: { label: "Ошибка", tone: DANGER },
  cancelled: { label: "Отменена", tone: MUTED },
};

/** ``WalletTransaction.kind`` — was leaking raw ``payment.refund`` /
 *  ``wallet_payment`` / ``admin.adjust`` in the wallet + Customer 360 feeds. */
const WALLET_TX_KIND: Record<string, StatusMeta> = {
  "admin.adjust": { label: "Ручная корректировка", tone: WARNING },
  wallet_payment: { label: "Оплата кошельком", tone: INFO },
  "payment.refund": { label: "Возврат платежа", tone: INFO },
  "promo.redeem": { label: "Погашение промокода", tone: ACCENT },
  merchant_deposit_credit: { label: "Пополнение депозита", tone: SUCCESS },
};

/** ``Merchant.status`` — the B2B reseller lifecycle (merchants feature). */
const MERCHANT_STATUS: Record<string, StatusMeta> = {
  active: { label: "Активен", tone: SUCCESS },
  frozen: { label: "Заморожен", tone: DANGER },
};

/** Review moderation status — filter values + status column. */
const REVIEW_STATUS: Record<string, StatusMeta> = {
  published: { label: "Опубликован", tone: SUCCESS },
  hidden: { label: "Скрыт", tone: WARNING },
  removed: { label: "Удалён", tone: DANGER },
};

export type StatusDomain =
  | "orderStatus"
  | "paymentStatus"
  | "eventKind"
  | "fulfillmentState"
  | "taskStatus"
  | "walletTxKind"
  | "reviewStatus"
  | "merchantStatus";

const REGISTRY: Record<StatusDomain, Record<string, StatusMeta>> = {
  orderStatus: fromLabelTone(ORDER_LABEL, ORDER_TONE),
  paymentStatus: fromLabelTone(PAYMENT_LABEL, PAYMENT_TONE),
  eventKind: EVENT_KIND,
  fulfillmentState: FULFILLMENT_STATE,
  taskStatus: TASK_STATUS,
  walletTxKind: WALLET_TX_KIND,
  reviewStatus: REVIEW_STATUS,
  merchantStatus: MERCHANT_STATUS,
};

/** Humanize an unmapped raw value instead of rendering it blank or in raw
 *  dev-only snake_case/dot-notation — e.g. ``order.something_new`` →
 *  ``something new``. A missing map entry means a new backend value should
 *  be added above, not that the operator should see nothing. */
function humanize(value: string): string {
  const tail = value.includes(".") ? (value.split(".").pop() ?? value) : value;
  return tail.replace(/_/g, " ");
}

/** Resolve a raw backend status/event value to a localized label + tone.
 *  The single entry point every status/event badge in the admin SPA routes
 *  through. */
export function localizeStatus(domain: StatusDomain, value: string): StatusMeta {
  return REGISTRY[domain][value] ?? { label: humanize(value), tone: MUTED };
}

interface StatusChipProps {
  domain: StatusDomain;
  value: string;
  className?: string;
}

/** Localized + colored status/event pill — the default rendering for any
 *  status or event-kind value in the admin SPA (see module docstring). */
export function StatusChip({ domain, value, className }: StatusChipProps) {
  const { label, tone } = localizeStatus(domain, value);
  return (
    <Badge tone={tone} dot {...(className ? { className } : {})}>
      {label}
    </Badge>
  );
}
