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

/**
 * Account kinds rendered as chips on the wallet page.
 *
 * Cashback and promo credit are hidden from the customer-facing UI until
 * the matching earn / spend flows are live — they're tracked in the
 * ledger but showing an inert ``0 USD`` chip just confused early users.
 * The full list still lives in ``UserAccountKind`` so the history view
 * keeps signing deltas correctly when those legs do move.
 */
export const VISIBLE_ACCOUNT_KINDS: UserAccountKind[] = ["user_wallet"];

/** Full list including the currently-hidden kinds. Use for ledger logic. */
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

// ---------- transactions / history ----------

export type Direction = "D" | "C";

export interface Posting {
  id: string;
  account_id: string;
  direction: Direction;
  amount: string;
  currency: string;
  created_at: string;
}

export interface WalletTransaction {
  id: string;
  kind: string;
  reference_type: string | null;
  reference_id: string | null;
  actor: string | null;
  extra_metadata: Record<string, unknown>;
  created_at: string;
  postings: Posting[];
}

interface TransactionListOut {
  items: WalletTransaction[];
}

/**
 * One row of the user-facing history list.
 *
 * The ledger stores transactions as double-entry pairs; from the user's
 * perspective only one leg is relevant — the one touching their own
 * account. ``delta`` is signed in user's favour: positive = balance went
 * up (cashback, refund, admin credit), negative = balance went down
 * (clawback, spend).
 */
export interface UserTransactionView {
  id: string;
  /** Account kind that moved (user_wallet / user_cashback / user_promo_credit). */
  accountKind: UserAccountKind;
  /** Signed amount in account currency. */
  delta: number;
  currency: string;
  /** Transaction kind from the backend (admin.adjust, payment.refund, …). */
  kind: string;
  /** Short label suitable for the row's headline. */
  label: string;
  reason: string | null;
  createdAt: string;
}

export const TX_KIND_LABEL: Record<string, string> = {
  "admin.adjust": "Корректировка от админа",
  "payment.refund": "Возврат за заказ",
  "order.payment": "Оплата заказа",
  "cashback.grant": "Кэшбэк за покупку",
  "promo.grant": "Промо-кредит",
  "topup": "Пополнение",
};

export function txKindLabel(kind: string): string {
  return TX_KIND_LABEL[kind] ?? kind;
}

/**
 * Project a raw double-entry transaction onto a single user-facing row.
 *
 * Returns ``null`` when the transaction did not touch any of the user's
 * accounts (defence-in-depth — the backend already filters this server-
 * side, so in practice every row that arrives should produce a view).
 *
 * Sign convention: all three user-side kinds (wallet / cashback / promo)
 * are normal-D, so a ``D`` posting on one of them increases the balance
 * (delta > 0), and ``C`` decreases it (delta < 0).
 */
export function summarizeForUser(
  tx: WalletTransaction,
  userAccountIds: ReadonlySet<string>,
  accountKindById: ReadonlyMap<string, UserAccountKind>,
): UserTransactionView | null {
  const userLeg = tx.postings.find((p) => userAccountIds.has(p.account_id));
  if (!userLeg) return null;
  const amount = Number.parseFloat(userLeg.amount) || 0;
  const delta = userLeg.direction === "D" ? amount : -amount;
  const kind = accountKindById.get(userLeg.account_id);
  if (!kind) return null;
  const reasonRaw = tx.extra_metadata.reason;
  return {
    id: tx.id,
    accountKind: kind,
    delta,
    currency: userLeg.currency,
    kind: tx.kind,
    label: txKindLabel(tx.kind),
    reason: typeof reasonRaw === "string" ? reasonRaw : null,
    createdAt: userLeg.created_at,
  };
}

export function useWalletTransactions(limit = 20) {
  const me = useMe();
  return useQuery<WalletTransaction[]>({
    queryKey: ["wallet", "transactions", me.data?.id ?? null, limit],
    enabled: Boolean(me.data),
    queryFn: async () => {
      const data = await apiGet<TransactionListOut>(
        `/api/v1/wallet/transactions?limit=${limit.toString()}`,
      );
      return data.items;
    },
    staleTime: 30_000,
  });
}

/**
 * Sum the visible user-side accounts converted into ``target`` via ``rate``.
 *
 * "Visible" means: kinds in :data:`VISIBLE_ACCOUNT_KINDS`. While cashback
 * and promo credit are hidden the header pill must reflect only what the
 * customer can actually see; otherwise the chip shows 5 USD while the
 * page below shows 0 USD and the discrepancy looks like a bug.
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
    (sum, b) =>
      b.currency === "USD" && VISIBLE_ACCOUNT_KINDS.includes(b.kind)
        ? sum + b.amount
        : sum,
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
