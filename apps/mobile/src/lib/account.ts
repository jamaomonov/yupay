/**
 * The account's balance, its history, top-ups and promo codes, as the signed-in user.
 */
import { ApiError } from "@yupay/api-client";
import type { MeOut, PaymentOut, WalletOverviewOut } from "@yupay/api-client/types";
import { useQuery } from "@tanstack/react-query";

import { newKey } from "@/lib/orders";
import type { PayMethod } from "@/lib/checkout";
import { authRequest } from "@/lib/session";
import type { LedgerTransaction } from "@/lib/wallet";

const V1 = "/api/v1";
const WEB_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://yupay.uz";

/** How the account is called on screen. */
export function accountName(user: MeOut): string {
  return user.display_name ?? user.email ?? "YuPay";
}

/** The spendable balance in soʻm: the `user_wallet` account, as on the website. */
export function spendable(overview: WalletOverviewOut | undefined): string | null {
  if (overview === undefined) return null;
  const row = overview.balances.find((b) => b.kind === "user_wallet" && b.currency === "UZS");
  return row?.balance ?? "0";
}

export function useWallet() {
  return useQuery({
    queryKey: ["account", "wallet"],
    queryFn: () => authRequest<WalletOverviewOut>(`${V1}/wallet`),
    staleTime: 30_000,
  });
}

/** The ids of the buyer's own ledger accounts: the history shows only their legs. */
export function accountIds(overview: WalletOverviewOut | undefined): Set<string> {
  return new Set((overview?.balances ?? []).map((b) => b.account_id));
}

export function useWalletHistory() {
  return useQuery({
    queryKey: ["account", "wallet", "history"],
    queryFn: () =>
      authRequest<{ items: LedgerTransaction[] }>(`${V1}/wallet/transactions?limit=50`),
    staleTime: 30_000,
  });
}

/**
 * Starts a deposit (`POST /wallet/topup`); the balance moves when the acquirer settles. The
 * caller keeps one key per amount and method, so a retry replays instead of opening a second
 * top-up. The acquirer returns the buyer to the website's wallet page — the one origin the API
 * accepts; the app reads the balance itself once the browser closes.
 */
export function createTopUp(input: {
  amount: number;
  provider: PayMethod;
  locale: string;
  idempotencyKey: string;
}): Promise<PaymentOut> {
  const prefix = input.locale === "ru" ? "" : `/${input.locale}`;
  return authRequest<PaymentOut>(`${V1}/wallet/topup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": input.idempotencyKey,
      "X-Yupay-Surface": "mobile",
    },
    body: JSON.stringify({
      amount: input.amount.toString(),
      provider: input.provider,
      return_url: `${WEB_URL.replace(/\/$/, "")}${prefix}/account/wallet?topup=1`,
    }),
  });
}

export interface Redeemed {
  code: string;
  amount: string;
  currency: string;
}

export function redeemPromo(code: string): Promise<Redeemed> {
  return authRequest<Redeemed>(`${V1}/promo/redeem`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": newKey() },
    body: JSON.stringify({ code: code.trim() }),
  });
}

/** `promo.<key>` for a refusal, from the machine-readable `code` the API tags 409s with. */
export function promoErrorKey(err: unknown): string {
  if (!(err instanceof ApiError)) return "promo.error";
  if (err.status === 404) return "promo.notFound";
  if (err.status === 429) return "auth.tooMany";
  if (err.status !== 409) return "promo.error";
  let code: unknown;
  try {
    code = (JSON.parse(err.body) as { code?: unknown }).code;
  } catch {
    code = undefined;
  }
  switch (code) {
    case "already_redeemed":
      return "promo.alreadyUsed";
    case "expired":
      return "promo.expired";
    case "exhausted":
      return "promo.exhausted";
    case "inactive":
      return "promo.inactive";
    default:
      return "promo.used";
  }
}
