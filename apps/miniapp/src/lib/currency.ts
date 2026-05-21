/**
 * Display currency: which fiat / USDT the catalog prices and the wallet
 * balance are shown in.
 *
 * Source of truth is the user row on the backend (``users.display_currency``).
 * We do **not** keep a parallel Zustand store anymore — the previous
 * localStorage-only version drifted between devices and never propagated to
 * the wallet, which kept showing USD regardless. The setter goes through
 * ``PATCH /api/v1/users/me`` and optimistically patches the ``/auth/me``
 * cache so the UI flips instantly.
 *
 * Affects ``useProductWithSkus`` (passes ``?currency=`` to the API) and the
 * wallet hero on the Wallet page (FX-converted via ``useFxRate``).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiPatch } from "./api";
import { useMe, type Me } from "./auth";

export const DISPLAY_CURRENCIES = ["USD", "UZS", "RUB", "USDT"] as const;
export type DisplayCurrency = (typeof DISPLAY_CURRENCIES)[number];

export const CURRENCY_LABEL: Record<DisplayCurrency, string> = {
  USD: "Доллар США",
  UZS: "Узбекский сум",
  RUB: "Российский рубль",
  USDT: "Tether USDT",
};

export const CURRENCY_SYMBOL: Record<DisplayCurrency, string> = {
  USD: "$",
  UZS: "сум",
  RUB: "₽",
  USDT: "USDT",
};

function isDisplayCurrency(value: string | undefined | null): value is DisplayCurrency {
  return (
    value != null && (DISPLAY_CURRENCIES as readonly string[]).includes(value)
  );
}

/**
 * Returns the active display currency. Falls back to ``USD`` whenever the
 * user isn't loaded yet or the stored value is one we no longer support.
 */
export function useDisplayCurrency(): DisplayCurrency {
  const me = useMe();
  const value = me.data?.display_currency;
  return isDisplayCurrency(value) ? value : "USD";
}

/**
 * Mutation that flips the user's display currency. Optimistically patches
 * the ``/auth/me`` cache so the whole UI updates in the same frame the user
 * taps an option, then awaits the PATCH and invalidates wallet/catalog
 * queries (their result shapes depend on the chosen currency).
 */
export function useUpdateDisplayCurrency() {
  const qc = useQueryClient();
  return useMutation<Me, Error, DisplayCurrency, { previous?: Me }>({
    mutationFn: async (currency) =>
      apiPatch<Me>("/api/v1/users/me", { display_currency: currency }),
    onMutate: async (currency) => {
      await qc.cancelQueries({ queryKey: ["me"] });
      const previous = qc.getQueryData<Me>(["me"]);
      if (previous) {
        qc.setQueryData<Me>(["me"], { ...previous, display_currency: currency });
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(["me"], ctx.previous);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["me"] });
      // Catalog responses bake the chosen currency into ``display_price`` —
      // they need a refetch on switch. Wallet shows a derived total too.
      void qc.invalidateQueries({ queryKey: ["brand"] });
      void qc.invalidateQueries({ queryKey: ["product"] });
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    },
  });
}
