/**
 * Wallet rules that do not touch the network: top-up bounds, the history row the buyer sees,
 * whether the balance covers an order. Plain TS, unit-tested. The same rules as the website's
 * `lib/wallet.ts` and `lib/wallet-balance.ts`.
 */

/** `POST /wallet/topup` bounds in soʻm, as the website enforces them. */
export const TOP_UP_MIN = 5_000;
export const TOP_UP_MAX = 5_000_000;

/** Round amounts a buyer would actually send. */
export const QUICK_AMOUNTS = [50_000, 100_000, 250_000, 500_000] as const;

/** Digits only: "100 000" and "100000.50" both read as whole soʻm typed so far. */
export function amountOf(text: string): number {
  const whole = text.split(/[.,]/)[0] ?? "";
  const digits = whole.replace(/\D/g, "").slice(0, 9);
  return digits === "" ? 0 : Number(digits);
}

export type AmountCheck = "empty" | "low" | "high" | "ok";

export function checkAmount(amount: number): AmountCheck {
  if (amount === 0) return "empty";
  if (amount < TOP_UP_MIN) return "low";
  if (amount > TOP_UP_MAX) return "high";
  return "ok";
}

export interface Posting {
  account_id: string;
  direction: "D" | "C";
  amount: string;
  currency: string;
  created_at: string;
}

export interface LedgerTransaction {
  id: string;
  kind: string;
  reference_type: string | null;
  reference_id: string | null;
  created_at: string;
  postings: Posting[];
}

/** One history row: `delta` is signed in the buyer's favour. */
export interface HistoryRow {
  id: string;
  delta: number;
  kind: string;
  at: string;
  orderId: string | null;
}

/**
 * The leg that touched the buyer's own account. `user_wallet` is a normal-D account: a `D`
 * posting raises the balance, a `C` lowers it.
 */
export function historyRow(
  tx: LedgerTransaction,
  accountIds: ReadonlySet<string>,
): HistoryRow | null {
  const leg = tx.postings.find((p) => accountIds.has(p.account_id));
  if (leg === undefined) return null;
  const amount = Number(leg.amount) || 0;
  return {
    id: tx.id,
    delta: leg.direction === "D" ? amount : -amount,
    kind: tx.kind,
    at: leg.created_at,
    orderId: tx.reference_type === "order" ? tx.reference_id : null,
  };
}

/** Ledger kind → `wallet.tx.<key>`; an unknown kind reads as a plain «operation». */
const KIND_KEYS: Record<string, string> = {
  topup: "topUp",
  "topup.refund": "topUpRefund",
  wallet_payment: "payment",
  "payment.refund": "refund",
  "promo.redeem": "promo",
  "cashback.grant": "cashback",
  "admin.adjust": "adjust",
};

export function kindKey(kind: string): string {
  return `wallet.tx.${KIND_KEYS[kind] ?? "other"}`;
}

/** What the «from balance» option can offer for an order of `price` soʻm. */
export type BalanceOption =
  | { state: "unknown" }
  | { state: "ready" }
  | { state: "short"; missing: number };

export function balanceOption(balance: string | null, price: string): BalanceOption {
  if (balance === null) return { state: "unknown" };
  const have = Number(balance);
  const need = Number(price);
  if (!Number.isFinite(have) || !Number.isFinite(need)) return { state: "unknown" };
  return have >= need ? { state: "ready" } : { state: "short", missing: Math.ceil(need - have) };
}
