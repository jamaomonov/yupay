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
 * Summed balance across the three user-side accounts in one display currency.
 * Real implementation would FX-convert; for now we assume USD across the
 * board and just total. Callers can override the currency for display.
 */
export function totalDisplayBalance(
  balances: ParsedBalance[],
): { amount: number; currency: string } {
  if (balances.length === 0) return { amount: 0, currency: "USD" };
  const wallet = balances.find((b) => b.kind === "user_wallet");
  const currency = wallet?.currency ?? balances[0]?.currency ?? "USD";
  const same = balances.filter((b) => b.currency === currency);
  return {
    amount: same.reduce((s, b) => s + b.amount, 0),
    currency,
  };
}

export function formatBalance(amount: number, currency: string): string {
  if (currency === "USD" || currency === "USDT") {
    return `$${amount.toFixed(2)}`;
  }
  return `${amount.toLocaleString("ru", { maximumFractionDigits: 2 })} ${currency}`;
}
