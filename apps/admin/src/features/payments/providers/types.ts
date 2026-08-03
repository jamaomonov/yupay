/**
 * Types for the admin payment-providers control screen
 * (`/payments/providers`).
 *
 * Mirrors the backend DTOs in
 * `apps/api/src/yupay/modules/payments/schemas.py` — `AdminProviderSummary`,
 * `AdminProviderListOut`, `AdminProviderDetailOut`, `VolumeRow`,
 * `SuccessRateOut`, `RecentPaymentOut`, `ProviderIncidentsOut` — see
 * `docs/api/openapi.json` for the generated shapes. Hand-written rather than
 * pulled from `@yupay/api-client`: the admin SPA's established convention
 * (see `features/fulfillment/types.ts`, `features/payments/types.ts`) is a
 * thin hand-written DTO layer next to the fetch calls, not the generated SDK.
 */

import type { PaymentStatus } from "@/features/payments/types";

/** Admin-controlled lifecycle state for one logical payment provider. */
export type ProviderState = "active" | "disabled" | "maintenance";

/** Analytics window accepted by `GET /admin/payments/providers/{provider}`. */
export type AnalyticsWindow = "today" | "7d" | "30d";

export interface AdminProviderSummary {
  provider: string;
  display_name: string;
  slugs: string[];
  config_available: boolean;
  state: ProviderState;
  changed_by: string | null;
  changed_at: string | null;
}

export interface AdminProviderListOut {
  providers: AdminProviderSummary[];
}

/** Payment volume for one currency within the analytics window. */
export interface VolumeRow {
  currency: string;
  amount: string;
  count: number;
}

/** Succeeded / failed / pending counts + success percentage for the window. */
export interface SuccessRateOut {
  succeeded: number;
  failed: number;
  pending: number;
  success_pct: number;
}

/** One payment row for the admin detail screen's recent list. */
export interface RecentPaymentOut {
  id: string;
  order_id: string;
  status: PaymentStatus;
  amount: string;
  currency: string;
  created_at: string;
}

/** Stuck-pending + failed-webhook counts for a provider group. */
export interface ProviderIncidentsOut {
  stuck_pending: number;
  failed_webhooks: number;
}

/** Full analytics detail for one logical payment provider (admin screen). */
export interface AdminProviderDetailOut {
  summary: AdminProviderSummary;
  volume: VolumeRow[];
  success_rate: SuccessRateOut;
  recent: RecentPaymentOut[];
  incidents: ProviderIncidentsOut;
}

/** Body of `PUT /admin/payments/providers/{provider}/state`. */
export interface SetProviderStateIn {
  state: ProviderState;
}

export const STATE_LABEL: Record<ProviderState, string> = {
  active: "Активен",
  disabled: "Отключён",
  maintenance: "Тех. работы",
};

export const STATE_TONE: Record<ProviderState, string> = {
  active: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  disabled: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  maintenance: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
};

export const WINDOW_LABEL: Record<AnalyticsWindow, string> = {
  today: "Сегодня",
  "7d": "7 дней",
  "30d": "30 дней",
};

export const WINDOWS: AnalyticsWindow[] = ["today", "7d", "30d"];
