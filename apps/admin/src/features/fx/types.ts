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

export interface ProviderQuoteOut {
  quote: string;
  rate: string | null;
  error: string | null;
}

export interface ProviderChainItemOut {
  slug: string;
  title: string;
  kind: string;
  enabled: boolean;
  configured: boolean;
  /** `| string` was here too, which erased the union — every literal was
   *  "overridden by string" and the exhaustive check below could never fail.
   *  `probe_chain` assigns exactly these four. */
  role: "primary" | "fallback" | "off" | "unconfigured";
  sort_order: number;
  quotes: ProviderQuoteOut[];
}

export interface ProviderChainOut {
  quotes: string[];
  items: ProviderChainItemOut[];
}
