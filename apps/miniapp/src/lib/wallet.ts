/**
 * Wallet hooks: balances + top-up.
 *
 * ``GET /api/v1/wallet`` returns the customer's own accounts (user_wallet,
 * user_cashback, user_promo_credit) with their computed balances. Top-up isn't
 * a real backend endpoint yet — the skeleton's submit handler is a toast.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./api";
import { useMe } from "./auth";
import { CURRENCY_SYMBOL, type DisplayCurrency } from "./currency";

export type UserAccountKind =
  | "user_wallet"
  | "user_cashback"
  | "user_promo_credit";

export interface BalanceOut {
  account_id: string;
  kind: UserAccountKind;
  currency: string;
  balance: string;
}

interface WalletOverviewOut {
  balances: BalanceOut[];
}

export interface ParsedBalance {
  kind: UserAccountKind;
  currency: string;
  amount: number;
  raw: BalanceOut;
}

export const ACCOUNT_META: Record<
  UserAccountKind,
  { label: string; description: string; tone: "primary" | "amber" | "violet" }
> = {
  user_wallet: {
    label: "Кошелёк",
    description: "Основной баланс, тратится на любые услуги",
    tone: "primary",
  },
  user_cashback: {
    label: "Кэшбэк",
    description: "Возврат за покупки — копится автоматически",
    tone: "amber",
  },
  user_promo_credit: {
    label: "Промо",
    description: "Промо-кредиты и реферальные бонусы",
    tone: "violet",
  },
};

export const ACCOUNT_ORDER: UserAccountKind[] = [
  "user_wallet",
  "user_cashback",
  "user_promo_credit",
];

export function useWallet() {
  const me = useMe();
  return useQuery<ParsedBalance[]>({
    queryKey: ["wallet", me.data?.id ?? null],
    enabled: Boolean(me.data),
    queryFn: async () => {
      const data = await apiGet<WalletOverviewOut>("/api/v1/wallet");
      return data.balances
        .filter((b) =>
          ACCOUNT_ORDER.includes(b.kind as UserAccountKind),
        )
        .map((b) => ({
          kind: b.kind,
          currency: b.currency,
          amount: Number.parseFloat(b.balance) || 0,
          raw: b,
        }));
    },
    staleTime: 30_000,
  });
}

/**
 * Sum the three user-side accounts converted into ``target`` via ``rate``.
 *
 * All wallet accounts currently store USD natively, so ``rate`` is the
 * USD→target multiplier (1 for USD/USDT). When ``rate === null`` we treat
 * the result as "not ready yet" so the caller can show a placeholder
 * instead of a misleading 0.
 */
export function totalDisplayBalance(
  balances: ParsedBalance[],
  target: DisplayCurrency,
  rate: number | null,
): { amount: number; currency: DisplayCurrency; ready: boolean } {
  if (rate === null) {
    return { amount: 0, currency: target, ready: false };
  }
  const usd = balances.reduce(
    (sum, b) => (b.currency === "USD" ? sum + b.amount : sum),
    0,
  );
  return { amount: usd * rate, currency: target, ready: true };
}

/**
 * Convert a USD amount into the target currency given a fresh rate. Pure
 * helper so the wallet hero and the per-account cards stay consistent.
 */
export function convertFromUsd(amountUsd: number, rate: number): number {
  return amountUsd * rate;
}

const _RU_FORMATTERS: Partial<Record<DisplayCurrency, Intl.NumberFormat>> = {};

function getFormatter(currency: DisplayCurrency): Intl.NumberFormat {
  let cached = _RU_FORMATTERS[currency];
  if (!cached) {
    // We render the symbol ourselves (Telegram's font sometimes mangles ₽);
    // the formatter is just here for grouping/decimals.
    const fractionDigits = currency === "UZS" ? 0 : 2;
    cached = new Intl.NumberFormat("ru-RU", {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    });
    _RU_FORMATTERS[currency] = cached;
  }
  return cached;
}

export function formatBalance(amount: number, currency: DisplayCurrency): string {
  const formatted = getFormatter(currency).format(amount);
  if (currency === "USD") return `$${formatted}`;
  if (currency === "USDT") return `${formatted} USDT`;
  return `${formatted} ${CURRENCY_SYMBOL[currency]}`;
}
