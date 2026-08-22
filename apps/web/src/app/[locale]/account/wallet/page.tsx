"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Wallet } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { use, useState } from "react";

import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";
import {
  formatLedgerAmount,
  getWallet,
  getWalletTransactions,
  summarizeForUser,
  txKindLabelKey,
  WALLET_CURRENCY,
  type UserTransactionView,
} from "@/lib/wallet";
import { spendableBalance } from "@/lib/wallet-balance";
import { useLoginModal } from "@/store/useLoginModal";

/** One page of history. Fifty was a silent truncation for an active customer. */
const PAGE = 25;

export default function WalletPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const t = useTranslations("web.wallet");
  const tNav = useTranslations("web.nav");
  const { user, isLoading: authLoading } = useAuth();

  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: Boolean(user),
  });
  const [limit, setLimit] = useState(PAGE);
  const history = useQuery({
    queryKey: ["wallet", "transactions", limit],
    queryFn: () => getWalletTransactions(limit),
    enabled: Boolean(user),
  });
  // The acquirer returns here after a top-up. The ledger only posts on
  // settlement, so for a beat the balance is the old one and the history is
  // unchanged — say so rather than let it read as a payment that vanished.
  const justToppedUp = useSearchParams().get("topup") !== null;
  const openLogin = useLoginModal((st) => st.open);

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
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <button type="button" onClick={openLogin} className={buttonStyles({ size: "md" })}>
              {tNav("login")}
            </button>
            <Link
              href={pathFor(locale, "/store")}
              className={buttonStyles({ variant: "ghost", size: "md" })}
            >
              {t("toCatalog")}
            </Link>
          </div>
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

      {justToppedUp && (
        <p className="border-primary/30 bg-primary/10 text-tx-mute mb-4 rounded-2xl border p-4 text-sm leading-relaxed">
          {t("topUpNote")}
        </p>
      )}

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
            <li key={row.id}>
              <RowBody row={row} locale={locale} t={t} />
            </li>
          ))}
        </ul>
      )}

      {rows.length >= limit && (
        <button
          type="button"
          onClick={() => {
            setLimit((n) => n + PAGE);
          }}
          className={buttonStyles({ variant: "ghost", size: "md", className: "mt-3 w-full" })}
        >
          {t("historyMore")}
        </button>
      )}
    </main>
  );
}

/** A history row, linked to its order when it has one. */
function RowBody({
  row,
  locale,
  t,
}: {
  row: UserTransactionView;
  locale: string;
  t: ReturnType<typeof useTranslations<"web.wallet">>;
}) {
  const body = (
    <span className="flex items-center gap-3 p-4">
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
        {formatLedgerAmount(locale, Math.abs(row.delta), row.currency)}
      </span>
    </span>
  );

  // A movement that names an order is a link to it; the orders list beside
  // this page has always worked that way.
  return row.orderId ? (
    <Link
      href={pathFor(locale, `/orders/${row.orderId}`)}
      className="hover:bg-card-2 block transition"
    >
      {body}
    </Link>
  ) : (
    body
  );
}
