/**
 * Skin sales and margin — the DTO of `GET /admin/skins/summary`
 * (`apps/api/src/yupay/modules/skins/admin_reports.py`). Money is USD decimal strings.
 */

import { apiGet } from "@/lib/api";

export interface SalesTotals {
  count: number;
  revenue_usd: string;
  cost_usd: string;
  margin_usd: string;
}

export interface SalesDay {
  /** A Tashkent calendar day, `YYYY-MM-DD`. */
  day: string;
  count: number;
  revenue_usd: string;
  margin_usd: string;
}

export interface SkinsSummaryOut {
  days: number;
  sold: SalesTotals;
  failed: SalesTotals;
  in_flight: SalesTotals;
  by_day: SalesDay[];
}

export const SALES_PERIODS = [7, 30, 90] as const;
export type SalesPeriod = (typeof SALES_PERIODS)[number];

export function fetchSummary(days: SalesPeriod): Promise<SkinsSummaryOut> {
  return apiGet<SkinsSummaryOut>(`/api/v1/admin/skins/summary?days=${String(days)}`);
}

/** Margin as a share of revenue, one decimal — `null` with no revenue. */
export function marginPercent(t: SalesTotals): string | null {
  const revenue = Number(t.revenue_usd);
  if (!revenue) return null;
  return `${((Number(t.margin_usd) / revenue) * 100).toFixed(1)} %`;
}
