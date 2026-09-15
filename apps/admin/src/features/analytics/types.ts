export type AnalyticsRange = "7d" | "30d" | "90d";

export interface RevenuePoint {
  date: string;
  revenue_usd: string;
  orders: number;
  /** Approximate, same basis as the summary. `null` when nothing that day had
   *  a cost we know — which is not the same as a zero margin. */
  margin_usd: string | null;
  /** Units that day whose cost is unknown, so a thin margin is
   *  distinguishable from an incomplete one. */
  margin_unknown_units: number;
}
export interface FunnelOut {
  created: number;
  paid: number;
  fulfilling: number;
  delivered: number;
  cancelled: number;
  expired: number;
  refunded: number;
  payment_conversion_pct: number;
}
export interface BrandRevenue {
  slug: string;
  revenue_usd: string;
  units: number;
  margin_usd: string | null;
}
export interface SkuRevenue {
  sku_code: string;
  revenue_usd: string;
  units: number;
  margin_usd: string | null;
}
export interface LocaleCount {
  locale: string;
  users: number;
}
export interface NewUsersPoint {
  date: string;
  users: number;
}
export interface BusinessSummary {
  gmv_usd: string;
  orders: number;
  paid_orders: number;
  delivered_orders: number;
  aov_usd: string;
  gross_margin_usd: string;
  margin_pct: number;
  margin_approx: boolean;
  margin_unknown_units: number;
}
export interface Customers {
  new_users_series: NewUsersPoint[];
  guest_orders: number;
  registered_orders: number;
  repeat_rate_pct: number;
  top_locales: LocaleCount[];
}
export interface BusinessAnalytics {
  generated_at: string;
  /** `null` for an explicit window — every request the calendar makes. */
  range: AnalyticsRange | null;
  since: string | null;
  /** Exclusive. `null` means the window runs up to `generated_at`. */
  until: string | null;
  summary: BusinessSummary;
  revenue_series: RevenuePoint[];
  funnel: FunnelOut;
  top_brands: BrandRevenue[];
  top_skus: SkuRevenue[];
  customers: Customers;
}
export interface ProviderStat {
  provider: string;
  count: number;
  volume_usd: string;
  success_rate_pct: number;
}
export interface SupplierStat {
  supplier: string;
  total: number;
  success_rate_pct: number;
  avg_seconds: number | null;
  manual_count: number;
  avg_attempts: number;
}
export interface LowStock {
  sku_code: string;
  available: number;
}
export interface CostChange {
  sku_code: string;
  supplier_slug: string;
  cost_usdt: string;
  previous_cost_usdt: string | null;
  captured_at: string;
}
export interface OpsAnalytics {
  generated_at: string;
  range: AnalyticsRange;
  payments: ProviderStat[];
  stuck_pending: number;
  webhook_unhealthy: number;
  fulfillment: SupplierStat[];
  stuck_tasks: number;
  low_stock: LowStock[];
  expiring_soon: number;
  supplier_cost: CostChange[];
}
