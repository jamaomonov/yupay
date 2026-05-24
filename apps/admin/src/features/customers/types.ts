/**
 * Types mirroring the FastAPI ``CustomerOverviewOut`` DTO from
 * ``apps/api/src/yupay/modules/admin/schemas.py`` — keep them in sync until the
 * project switches to ``@hey-api/openapi-ts``.
 */

export type RiskFlag = "no_email" | "no_telegram" | "fresh_account" | "many_failed_payments";

export interface TelegramLinkOut {
  tg_user_id: number;
  tg_username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  is_premium: boolean;
  last_seen_at: string;
}

export interface CustomerUserOut {
  id: string;
  email: string | null;
  locale: string;
  display_currency: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  telegram_link: TelegramLinkOut | null;
}

export interface CustomerOrderSummary {
  id: string;
  status: string;
  currency: string;
  total_charged: string;
  items_count: number;
  created_at: string;
  delivered_at: string | null;
}

export interface CustomerPaymentSummary {
  id: string;
  order_id: string;
  provider: string;
  status: string;
  amount: string;
  currency: string;
  external_id: string | null;
  created_at: string;
}

export interface CustomerTaskSummary {
  id: string;
  order_id: string;
  supplier: string;
  status: string;
  last_error: string | null;
  created_at: string;
}

export interface CustomerBalanceOut {
  account_id: string;
  kind: string;
  currency: string;
  balance: string;
}

export interface CustomerStatsOut {
  total_orders: number;
  delivered_orders: number;
  total_spent_usd: string;
  failed_payments: number;
}

export interface CustomerOverviewOut {
  user: CustomerUserOut;
  stats: CustomerStatsOut;
  recent_orders: CustomerOrderSummary[];
  recent_payments: CustomerPaymentSummary[];
  open_fulfillment_tasks: CustomerTaskSummary[];
  wallet_balances: CustomerBalanceOut[];
  risk_flags: RiskFlag[];
}

export const RISK_FLAG_LABEL: Record<RiskFlag, string> = {
  no_email: "Нет email",
  no_telegram: "Нет Telegram",
  fresh_account: "Новый аккаунт",
  many_failed_payments: "Много неуспешных платежей",
};

export const RISK_FLAG_TONE: Record<RiskFlag, "warn" | "muted"> = {
  no_email: "muted",
  no_telegram: "muted",
  fresh_account: "muted",
  many_failed_payments: "warn",
};
