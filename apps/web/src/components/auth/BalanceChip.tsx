"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

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
  const t = useTranslations("web.nav");
  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: Boolean(user),
    // The header is mounted on every page, so this must not be a per-navigation
    // request. Checkout invalidates the key after paying from the balance, and
    // a top-up leaves the tab entirely for the acquirer, so the window in which
    // a stale figure can be shown is bounded by those two rather than by luck.
    staleTime: 30_000,
  });

  if (!user) return null;
  const balance = spendableBalance(wallet.data?.balances ?? null, WALLET_CURRENCY);
  // A fixed-width placeholder rather than nothing: rendering the chip late
  // shifted every control beside it, which is the shift `AccountMenu` reserves
  // space to avoid.
  if (balance === null) return <div className="h-11 w-[92px] shrink-0" aria-hidden />;
  const formatted = formatUzs(locale, Math.round(balance));

  return (
    <Link
      href={pathFor(locale, "/account/wallet")}
      aria-label={`${t("wallet")}: ${formatted}`}
      // `shrink-0 whitespace-nowrap`: between md and ~1024px the header's
      // controls already fill the row, and a shrinkable chip wrapped its digits
      // onto two lines inside a fixed-height pill.
      className="border-border bg-muted text-tx-mute hover:text-foreground hover:border-primary/40 flex h-11 shrink-0 items-center whitespace-nowrap rounded-full border px-3.5 text-sm font-bold tabular-nums transition"
    >
      {formatted}
    </Link>
  );
}
