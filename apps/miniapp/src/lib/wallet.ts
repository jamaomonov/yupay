/**
 * Wallet hooks: balances + top-up.
 *
 * ``GET /api/v1/wallet`` returns the customer's own accounts (user_wallet,
 * user_cashback, user_promo_credit) with their computed balances.
 * ``POST /api/v1/wallet/topup`` starts an acquirer payment; the ledger credit
 * lands when that payment settles (ADR-0058).
 */

import { useQuery } from "@tanstack/react-query";

import type { MessageKey } from "@/lib/i18n";

import { getActiveLocale } from "@/lib/i18n/core";

import { apiGet, apiPost, newIdempotencyKey } from "./api";
import { useMe } from "./auth";
import { CURRENCY_SYMBOL, type DisplayCurrency } from "./currency";
import type { PaymentOut } from "./orders";

export type UserAccountKind = "user_wallet" | "user_cashback" | "user_promo_credit";

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
        .filter((b) => ACCOUNT_ORDER.includes(b.kind))
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

/** Start an acquirer payment that will credit ``user_wallet`` 1:1 when it settles.
 *
 * The key is the caller's to own, and deliberately not minted here: a fresh key
 * per call is a key that never deduplicates anything. A customer whose request
 * times out after the server accepted it would tap again and open a *second*
 * top-up order — the header would be present and useless. `topUpAttemptKey`
 * keeps one key alive for as long as the customer is asking for the same thing.
 */
export function createWalletTopUp(
  amount: number,
  provider: string,
  idempotencyKey: string,
): Promise<PaymentOut> {
  return apiPost<PaymentOut>(
    "/api/v1/wallet/topup",
    { amount: amount.toString(), provider },
    { idempotencyKey },
  );
}

/** One idempotency key per (amount, provider) the customer is asking for.
 *
 * Retrying the same request reuses it, so the server replays the original
 * payment instead of creating another. Changing the amount or the acquirer is
 * a different request and mints a new one. */
export function topUpAttemptKey(
  store: { current: { signature: string; key: string } | null },
  signature: string,
): string {
  if (store.current?.signature !== signature) {
    store.current = { signature, key: newIdempotencyKey("wallet-topup") };
  }
  return store.current.key;
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
  createdAt: string;
}

/**
 * Ledger transaction kind → label. Keys MUST mirror the ``kind=`` values the
 * backend passes to ``wallet.post`` — an unlisted kind falls through to the raw
 * ledger string in the customer's history (that's how ``promo.redeem`` and
 * ``wallet_payment`` both slipped out). ``wallet.test.ts`` pins the mapping.
 *
 * Posted today: admin.adjust (wallet/service.py), payment.refund
 * (payments/service.py), wallet_payment (payments/gateways/wallet.py),
 * promo.redeem (promo/service.py).
 */
export const TX_KIND_LABEL: Record<string, MessageKey> = {
  "admin.adjust": "wallet.tx.adminAdjust",
  "payment.refund": "wallet.tx.refund",
  // Paying an order from the wallet balance — reads as "Оплата заказа".
  wallet_payment: "wallet.tx.orderPayment",
  "promo.redeem": "wallet.tx.promo",
  "cashback.grant": "wallet.tx.cashback",
  topup: "wallet.tx.topup",
  "topup.refund": "wallet.tx.topupRefund",
};

/** Catalog key for a backend transaction kind, or ``null`` for unknown kinds
 *  (the caller then shows the raw kind). Resolution happens at render so the
 *  label follows the active locale. */
export function txKindLabelKey(kind: string): MessageKey | null {
  return TX_KIND_LABEL[kind] ?? null;
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
  return {
    id: tx.id,
    accountKind: kind,
    delta,
    currency: userLeg.currency,
    kind: tx.kind,
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
 * Group visible balances by currency. The user used to see a single
 * "converted" total that drifted with the FX rate; we now show each
 * native currency separately so 5.00 USD stays 5.00 USD no matter what
 * Click's UZS rate did overnight.
 *
 * "Visible" means kinds in :data:`VISIBLE_ACCOUNT_KINDS` — cashback and
 * promo credit are currently hidden from the customer-facing UI.
 *
 * Returns one entry per currency. Empty list means the user has no
 * visible accounts (the page should render an empty state rather than
 * "0 USD", which would be misleading once UZS top-up exists).
 */
export interface CurrencyBalance {
  amount: number;
  currency: string;
}

export function groupBalancesByCurrency(balances: ParsedBalance[]): CurrencyBalance[] {
  const acc = new Map<string, number>();
  for (const b of balances) {
    if (!VISIBLE_ACCOUNT_KINDS.includes(b.kind)) continue;
    acc.set(b.currency, (acc.get(b.currency) ?? 0) + b.amount);
  }
  return Array.from(acc.entries()).map(([currency, amount]) => ({
    amount,
    currency,
  }));
}

/**
 * Pick the "headline" balance for places that can only show one figure
 * (header pill, hero one-liner). Priority:
 *
 * 1. The user's ``preferred`` currency if it has a non-zero balance —
 *    matches the locale of the UI so a UZ user reads UZS first, even
 *    when they also happen to hold a legacy USD goodwill credit.
 * 2. Otherwise the largest non-zero balance by absolute value.
 * 3. Finally, ``preferred`` itself as a placeholder (0) so the hero
 *    has something to render before any top-up has happened.
 */
export function pickPrimaryBalance(
  groups: CurrencyBalance[],
  preferred: string,
): CurrencyBalance | null {
  const nonZero = groups.filter((g) => g.amount !== 0);
  const preferredHit = nonZero.find((g) => g.currency === preferred);
  if (preferredHit) return preferredHit;
  if (nonZero.length > 0) {
    return nonZero.reduce((max, g) => (Math.abs(g.amount) > Math.abs(max.amount) ? g : max));
  }
  return { amount: 0, currency: preferred };
}

/**
 * Convert a USD amount into the target currency given a fresh rate. Pure
 * helper so the wallet hero and the per-account cards stay consistent.
 */
export function convertFromUsd(amountUsd: number, rate: number): number {
  return amountUsd * rate;
}

const _FORMATTERS: Record<string, Intl.NumberFormat> = {};

function getFormatter(currency: string): Intl.NumberFormat {
  // Grouping and decimal separators are locale-specific, so the cache is
  // keyed by both locale and currency.
  const locale = getActiveLocale();
  const cacheKey = `${locale}:${currency}`;
  let cached = _FORMATTERS[cacheKey];
  if (!cached) {
    // We render the symbol ourselves (Telegram's font sometimes mangles ₽);
    // the formatter is just here for grouping/decimals. UZS and RUB are
    // whole-number currencies in practice, the rest keep 2 decimals.
    const fractionDigits = currency === "UZS" ? 0 : 2;
    cached = new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    });
    _FORMATTERS[cacheKey] = cached;
  }
  return cached;
}

/**
 * Format a balance in its **native** currency. Accepts any ISO-like
 * currency string (so unfamiliar values from the ledger don't crash the
 * UI) and falls back to ``<amount> <code>`` if there's no symbol mapped.
 */
export function formatBalance(amount: number, currency: string): string {
  const formatted = getFormatter(currency).format(amount);
  if (currency === "USD") return `$${formatted}`;
  if (currency === "USDT") return `${formatted} USDT`;
  const symbol = (CURRENCY_SYMBOL as Record<string, string | undefined>)[currency];
  return `${formatted} ${symbol ?? currency}`;
}
