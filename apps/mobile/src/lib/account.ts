/**
 * The account's balance and promo codes, as the signed-in user.
 */
import { ApiError } from "@yupay/api-client";
import type { MeOut, WalletOverviewOut } from "@yupay/api-client/types";
import { useQuery } from "@tanstack/react-query";

import { newKey } from "@/lib/orders";
import { authRequest } from "@/lib/session";

const V1 = "/api/v1";

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
