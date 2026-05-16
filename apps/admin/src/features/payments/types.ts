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
}
