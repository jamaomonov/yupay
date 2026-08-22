export interface AdminRateOut {
  base: string;
  quote: string;
  rate: string;
  fetched_at: string;
  source: string;
  use_manual: boolean;
  manual_rate: string | null;
  fx_rate: string | null;
  fx_source: string | null;
  fx_fetched_at: string | null;
}

export interface AdminRatesOut {
  base: string;
  rates: AdminRateOut[];
}
