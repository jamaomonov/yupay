export type PaymentStatus =
  | "pending"
  | "requires_action"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "refunded"
  | "partially_refunded";

export interface PaymentAttempt {
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  error: string | null;
  created_at: string;
}

export interface PaymentAdminOut {
  id: string;
  order_id: string;
  provider: string;
  status: PaymentStatus;
  amount: string;
  currency: string;
  intent_url: string | null;
  external_id: string | null;
  extra_metadata: Record<string, unknown>;
  created_at: string;
  succeeded_at: string | null;
  failed_at: string | null;
  attempts: PaymentAttempt[];
}

export interface PaymentAdminListOut {
  items: PaymentAdminOut[];
  total: number;
}

/** Localized labels — mirrors the Orders list's `STATUS_LABEL` pattern
 *  (`apps/admin/src/features/orders/types.ts`) so both surfaces read the
 *  same way. */
export const STATUS_LABEL: Record<PaymentStatus, string> = {
  pending: "Ожидание",
  requires_action: "Требуется действие",
  succeeded: "Успешно",
  failed: "Ошибка",
  cancelled: "Отменён",
  refunded: "Возврат",
  partially_refunded: "Частичный возврат",
};

export const STATUS_TONE: Record<PaymentStatus, string> = {
  pending: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  requires_action: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  succeeded: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  failed: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  cancelled: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  refunded: "bg-[var(--info-soft)] text-[var(--info-fg)]",
  partially_refunded: "bg-[var(--info-soft)] text-[var(--info-fg)]",
};
