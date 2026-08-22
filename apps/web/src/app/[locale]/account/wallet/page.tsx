"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Wallet } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { use } from "react";

import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";
import {
  getWallet,
  getWalletTransactions,
  summarizeForUser,
  txKindLabelKey,
  WALLET_CURRENCY,
  type UserTransactionView,
} from "@/lib/wallet";
import { spendableBalance } from "@/lib/wallet-balance";

export default function WalletPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const t = useTranslations("web.wallet");
  const { user, isLoading: authLoading } = useAuth();

  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: Boolean(user),
  });
  const history = useQuery({
    queryKey: ["wallet", "transactions"],
    queryFn: () => getWalletTransactions(50),
    enabled: Boolean(user),
  });

  if (authLoading) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        <Skeleton className="mb-6 h-9 w-48 rounded-lg" />
        <Skeleton className="h-40 rounded-2xl" />
      </main>
    );
  }

  // The wallet belongs to an account. Checkout is deliberately guest-friendly,
  // so this is the one place that asks for a sign-in rather than degrading.
  if (!user) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <Wallet size={32} className="text-tx-dim mx-auto mb-4" />
          <p className="text-tx-mute mb-5">{t("guestBody")}</p>
          <Link href={pathFor(locale, "/store")} className={buttonStyles({ size: "sm" })}>
            {t("toCatalog")}
          </Link>
        </div>
      </main>
    );
  }

  const balance = spendableBalance(wallet.data?.balances ?? null, WALLET_CURRENCY);
  // Only the account the headline counts. Building this from every balance
  // put cashback and promo movements above a figure that never moved.
  const accountIds = new Set(
    (wallet.data?.balances ?? [])
      .filter((b) => b.kind === "user_wallet" && b.currency === WALLET_CURRENCY)
      .map((b) => b.account_id),
  );
  const rows = (history.data?.items ?? [])
    .map((tx) => summarizeForUser(tx, accountIds))
    .filter((v): v is UserTransactionView => v !== null);

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>

      <section className="border-border bg-card mb-8 rounded-2xl border p-6">
        <p className="text-tx-dim mb-2 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
          {t("balanceLabel")}
        </p>
        {wallet.isError ? (
          <p className="text-sm text-red-400">{t("balanceError")}</p>
        ) : balance === null ? (
          <Skeleton className="h-10 w-40 rounded-lg" />
        ) : (
          <p className="font-display text-4xl font-bold tabular-nums tracking-[-0.02em]">
            {formatUzs(locale, Math.round(balance))}
          </p>
        )}
        <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("balanceNote")}</p>
        <Link
          href={pathFor(locale, "/account/wallet/top-up")}
          className={buttonStyles({ size: "md", className: "mt-5 w-full sm:w-auto" })}
        >
          {t("topUpCta")}
        </Link>
      </section>

      <h2 className="text-tx-dim mb-3 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
        {t("historyTitle")}
      </h2>

      {history.isLoading && <Skeleton className="h-24 rounded-2xl" />}
      {history.isError && <p className="text-sm text-red-400">{t("historyError")}</p>}

      {!history.isLoading && !history.isError && rows.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-8 text-center">
          <p className="text-tx-mute text-sm">{t("historyEmpty")}</p>
        </div>
      )}

      {rows.length > 0 && (
        <ul className="border-border bg-card divide-border divide-y overflow-hidden rounded-2xl border">
          {rows.map((row) => (
            <li key={row.id} className="flex items-center gap-3 p-4">
              <span
                className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full ${
                  row.delta >= 0 ? "bg-primary/15 text-primary" : "bg-muted text-tx-mute"
                }`}
              >
                {row.delta >= 0 ? <ArrowDownLeft size={16} /> : <ArrowUpRight size={16} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {/* An unmapped ledger kind shows raw rather than blank — that
                      is how a missing label gets noticed instead of hiding. */}
                  {txKindLabelKey(row.kind) ? t(txKindLabelKey(row.kind)!) : row.kind}
                </span>
                <span className="text-tx-dim block text-xs">
                  {new Intl.DateTimeFormat(locale, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(row.createdAt))}
                </span>
              </span>
              <span
                className={`flex-shrink-0 text-sm font-bold tabular-nums ${
                  // `text-tx-mute` is the app's disabled-control colour; a
                  // purchase is an ordinary row, not a greyed-out one.
                  row.delta >= 0 ? "text-primary" : "text-foreground"
                }`}
              >
                {row.delta >= 0 ? "+" : "−"}
                {formatUzs(locale, Math.round(Math.abs(row.delta)))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
