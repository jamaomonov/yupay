/**
 * Display currency: which fiat/USDT the catalog prices are shown in.
 *
 * Affects ``useProductWithSkus`` (passes ``?currency=`` to the API). Order
 * totals and wallet balances stay in their own native currency — switching
 * the display currency does not retro-convert old orders.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

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

interface CurrencyState {
  currency: DisplayCurrency;
  setCurrency: (c: DisplayCurrency) => void;
}

export const useCurrencyStore = create<CurrencyState>()(
  persist(
    (set) => ({
      currency: "USD",
      setCurrency: (currency) => set({ currency }),
    }),
    { name: "yupay.miniapp.display-currency" },
  ),
);
