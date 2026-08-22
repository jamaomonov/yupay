"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { useAuth } from "@/lib/auth";
import { formatUzs, pathFor } from "@/lib/seo";
import { getWallet, WALLET_CURRENCY } from "@/lib/wallet";
import { spendableBalance } from "@/lib/wallet-balance";

/**
 * The balance, in the header, for signed-in customers.
 *
 * Renders nothing at all for a guest or while the amount is unknown, rather
 * than a placeholder: the header is on every page, and a chip that appears a
 * beat late shifts the controls beside it. Nothing is better than a flicker.
 */
export function BalanceChip({ locale }: { locale: string }) {
  const { user } = useAuth();
  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: Boolean(user),
    // The header is mounted everywhere; a top-up or a wallet payment elsewhere
    // in the tab invalidates this key, so polling would only add noise.
    staleTime: 30_000,
  });

  if (!user) return null;
  const balance = spendableBalance(wallet.data?.balances ?? null, WALLET_CURRENCY);
  if (balance === null) return null;

  return (
    <Link
      href={pathFor(locale, "/account/wallet")}
      className="border-border bg-muted text-tx-mute hover:text-foreground hover:border-primary/40 flex h-11 items-center rounded-full border px-3.5 text-sm font-bold tabular-nums transition"
    >
      {formatUzs(locale, Math.round(balance))}
    </Link>
  );
}
