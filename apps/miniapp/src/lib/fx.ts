/**
 * FX helper for the storefront.
 *
 * The backend exposes ``GET /api/v1/fx/rates`` with USD as the base — we
 * only need the multiplier to turn a USD amount into the user's display
 * currency. Cached for 5 minutes since rates are USD→quote and don't
 * fluctuate fast enough to warrant aggressive refetching here.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./api";

import type { DisplayCurrency } from "./currency";

interface FxRateApi {
  base: string;
  quote: string;
  rate: string;
  fetched_at: string;
  source: string;
}

interface FxRatesApi {
  base: string;
  rates: FxRateApi[];
}

/**
 * Returns the conversion factor from USD into ``target``. ``USD``/``USDT``
 * resolve immediately to ``1`` without a network round-trip — convenient
 * when callers don't want to special-case those.
 *
 * ``ready`` flips to ``true`` only once we have a confirmed rate; until
 * then keep showing the USD amount instead of a "—".
 */
export function useFxRate(target: DisplayCurrency): {
  rate: number;
  ready: boolean;
} {
  const isPassthrough = target === "USD" || target === "USDT";

  const query = useQuery<number>({
    queryKey: ["fx", "rate", "USD", target],
    enabled: !isPassthrough,
    queryFn: async () => {
      const data = await apiGet<FxRatesApi>("/api/v1/fx/rates");
      const hit = data.rates.find(
        (r) => r.base === "USD" && r.quote === target,
      );
      if (!hit) {
        // Backend lists only the configured fx_supported_quotes. Failing
        // loudly is better than silently rendering a wrong number.
        throw new Error(`FX rate for USD → ${target} not available`);
      }
      const parsed = Number.parseFloat(hit.rate);
      if (!Number.isFinite(parsed) || parsed <= 0) {
        throw new Error(`Malformed FX rate: ${hit.rate}`);
      }
      return parsed;
    },
    staleTime: 5 * 60_000,
  });

  if (isPassthrough) {
    return { rate: 1, ready: true };
  }
  return { rate: query.data ?? 1, ready: query.isSuccess };
}
