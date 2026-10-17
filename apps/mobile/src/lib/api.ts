/**
 * The app's API calls: the storefront API through the shared `@yupay/api-client`.
 *
 * Prices are asked in UZS — the app's first version sells to Uzbekistan only (ADR-0100).
 */
import { createApiClient } from "@yupay/api-client";
import type {
  BrandDetailOut,
  BrandListOut,
  PlayerCheckOut,
  ProductDetailOut,
} from "@yupay/api-client/types";
import { useMutation, useQuery } from "@tanstack/react-query";

import type { Locale } from "@/lib/i18n";

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://api.yupay.uz";
const V1 = "/api/v1";

let currentLocale: Locale = "ru";

/** Called by the root layout so `Accept-Language` follows the chosen language. */
export function setApiLocale(locale: Locale): void {
  currentLocale = locale;
}

export const api = createApiClient({ baseUrl: BASE_URL, getLocale: () => currentLocale });

export function useBrands(locale: Locale) {
  return useQuery({
    queryKey: ["brands", locale],
    queryFn: () => api.request<BrandListOut>(`${V1}/catalog/brands`),
    staleTime: 5 * 60_000,
  });
}

export function useBrand(slug: string, locale: Locale) {
  return useQuery({
    queryKey: ["brand", slug, locale],
    queryFn: () => api.request<BrandDetailOut>(`${V1}/catalog/brands/${encodeURIComponent(slug)}`),
    staleTime: 5 * 60_000,
  });
}

export function useProduct(slug: string | undefined, locale: Locale) {
  return useQuery({
    queryKey: ["product", slug, locale],
    queryFn: () =>
      api.request<ProductDetailOut>(
        `${V1}/catalog/products/${encodeURIComponent(slug ?? "")}?currency=UZS`,
      ),
    enabled: Boolean(slug),
    staleTime: 60_000,
  });
}

/** `unsupported` is answered by brands with no player check; the generated type predates it. */
export type PlayerCheckStatus = PlayerCheckOut["status"] | "unsupported";

export interface PlayerCheckResult {
  status: PlayerCheckStatus;
  name?: string | null;
}

export function usePlayerCheck(brandSlug: string) {
  return useMutation({
    mutationFn: (input: { playerId: string; serverId?: string }) =>
      api.request<PlayerCheckResult>(
        `${V1}/catalog/brands/${encodeURIComponent(brandSlug)}/check-player`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: input.playerId, server_id: input.serverId ?? null }),
        },
      ),
  });
}
