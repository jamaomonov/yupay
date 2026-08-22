"use client";

/**
 * Wallet reads and top-up for the storefront.
 *
 * `GET /api/v1/wallet` returns the customer's own accounts with computed
 * balances; `POST /api/v1/wallet/topup` starts an acquirer payment that credits
 * `user_wallet` 1:1 once it settles (ADR-0058). Both need a signed-in user —
 * the wallet belongs to an account, and web checkout is otherwise guest-first.
 */

import { apiFetch } from "@/lib/client";
import { type WalletBalance } from "@/lib/wallet-balance";

/** The charge currency for every acquirer the storefront offers. */
export const WALLET_CURRENCY = "UZS";

export interface WalletOverviewOut {
  balances: WalletBalance[];
}

export type Direction = "D" | "C";

export interface Posting {
  id: string;
  account_id: string;
  direction: Direction;
  amount: string;
  currency: string;
  created_at: string;
}

/** The ledger stores double-entry pairs; the customer only cares about the leg
 *  that touched their own account. See `summarizeForUser`. */
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

export interface WalletTransactionListOut {
  items: WalletTransaction[];
}

/** One row of the customer-facing history. `delta` is signed in the customer's
 *  favour: positive means the balance went up. */
export interface UserTransactionView {
  id: string;
  delta: number;
  currency: string;
  kind: string;
  createdAt: string;
}

/**
 * Project a double-entry transaction onto the customer's single row.
 *
 * `null` when the transaction touched none of their accounts — the API already
 * filters server-side, so this is defence in depth rather than an expected case.
 *
 * Sign convention: `user_wallet` is a normal-D account, so a `D` posting raises
 * the balance and a `C` lowers it. Reading that backwards would show every
 * top-up as a withdrawal.
 */
export function summarizeForUser(
  tx: WalletTransaction,
  userAccountIds: ReadonlySet<string>,
): UserTransactionView | null {
  const leg = tx.postings.find((p) => userAccountIds.has(p.account_id));
  if (!leg) return null;
  const amount = Number.parseFloat(leg.amount) || 0;
  return {
    id: tx.id,
    delta: leg.direction === "D" ? amount : -amount,
    currency: leg.currency,
    kind: tx.kind,
    createdAt: leg.created_at,
  };
}

/**
 * Ledger kind → i18n key. Keys mirror the `kind=` values the backend passes to
 * `wallet.post`; an unlisted kind falls through to the raw ledger string in the
 * customer's history, which is how `promo.redeem` and `wallet_payment` once
 * leaked out in the mini app. The test pins the mapping.
 */
export const TX_KIND_LABEL: Record<string, string> = {
  "admin.adjust": "txAdminAdjust",
  "payment.refund": "txRefund",
  wallet_payment: "txOrderPayment",
  "promo.redeem": "txPromo",
  "cashback.grant": "txCashback",
  topup: "txTopUp",
  "topup.refund": "txTopUpRefund",
};

export function txKindLabelKey(kind: string): string | null {
  return TX_KIND_LABEL[kind] ?? null;
}

export interface PaymentOut {
  id: string;
  order_id: string;
  provider: string;
  status: string;
  amount: string;
  currency: string;
  intent_url: string | null;
  external_id: string | null;
}

export function getWallet(): Promise<WalletOverviewOut> {
  return apiFetch<WalletOverviewOut>("/wallet");
}

export function getWalletTransactions(limit = 50): Promise<WalletTransactionListOut> {
  return apiFetch<WalletTransactionListOut>(`/wallet/transactions?limit=${String(limit)}`);
}

/**
 * Start a deposit. The balance moves when the acquirer settles, not here.
 *
 * The key is the caller's: minting a fresh one per call makes the header
 * decorative, because the retry it exists to deduplicate carries a different
 * key and opens a second top-up order. See `topUpAttemptKey`.
 */
export function createWalletTopUp(
  amount: number,
  provider: string,
  idempotencyKey: string,
): Promise<PaymentOut> {
  return apiFetch<PaymentOut>("/wallet/topup", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: { amount: amount.toString(), provider },
  });
}

/** One idempotency key per (amount, provider) the customer is asking for.
 *
 * Retrying the same request reuses it, so the server replays the original
 * payment instead of creating another. Changing either is a different request
 * and mints a new key. */
export function topUpAttemptKey(
  store: { current: { signature: string; key: string } | null },
  signature: string,
): string {
  if (store.current?.signature !== signature) {
    store.current = { signature, key: `web-topup-${crypto.randomUUID()}` };
  }
  return store.current.key;
}

/** Amount bounds, mirroring `wallet.topup_limits._LIMITS` on the API.
 *
 * The server is still the authority — this only spares the customer a round
 * trip to be told no. An unrecognised currency blocks rather than guessing. */
export const TOP_UP_LIMITS: Record<string, { min: number; max: number }> = {
  UZS: { min: 10_000, max: 5_000_000 },
};

/** Round numbers a customer would actually transfer. */
export const QUICK_AMOUNTS: Record<string, number[]> = {
  UZS: [50_000, 100_000, 250_000, 500_000, 1_000_000],
};
