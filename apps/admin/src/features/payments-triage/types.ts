/**
 * Types mirroring `PaymentTriageOut` in apps/api/src/yupay/modules/admin/schemas.py.
 */

export interface PaymentTriageRow {
  id: string;
  order_id: string;
  user_id: string | null;
  guest_email: string | null;
  provider: string;
  status: string;
  amount: string;
  currency: string;
  created_at: string;
  waiting_minutes: number;
}

export interface WebhookTriageRow {
  id: string;
  provider: string;
  external_event_id: string;
  received_at: string;
  processed_at: string | null;
  signature_ok: boolean;
}

export interface PaymentTriageOut {
  threshold_minutes: number;
  stuck_pending: PaymentTriageRow[];
  failed_webhooks: WebhookTriageRow[];
}
