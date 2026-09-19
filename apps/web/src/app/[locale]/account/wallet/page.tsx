"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, use, useEffect, useState } from "react";

import { WalletMark } from "@/components/icons/WalletMark";
import { Skeleton } from "@/components/ui/Skeleton";
import { PromoCodeCard } from "@/components/wallet/PromoCodeCard";
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
    // "Показать ещё" mounts a new key, so without this the list unmounts, the
    // page collapses to a skeleton and re-expands — pagination that erases
    // what you were reading is worse than the cap it replaced.
    placeholderData: keepPreviousData,
  });
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
          <WalletMark size={32} className="text-tx-dim mx-auto mb-4" />
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
  // Every account the customer owns. Narrowing this to `user_wallet` kept
  // cashback and promo movements from sitting above a headline that had not
  // moved — but it also made them vanish from the history entirely, and a
  // credit the customer received should not be invisible. Each row carries
  // its own amount and currency, so the two can differ honestly.
  const accountIds = new Set((wallet.data?.balances ?? []).map((b) => b.account_id));
  const rows = (history.data?.items ?? [])
    .map((tx) => summarizeForUser(tx, accountIds))
    .filter((v): v is UserTransactionView => v !== null);

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>

      {/* `useSearchParams` bails this page out of the static export unless it
          sits behind a boundary — every other call site in this app is wrapped
          the same way. */}
      <Suspense fallback={null}>
        <ReturnedFromAcquirer note={t("topUpNote")} />
      </Suspense>

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

      {/* Promo code: credits user_wallet directly, so the balance card above
          moves the instant a redeem succeeds. The Mini App's wallet has
          carried this since it shipped; the web wallet didn't. */}
      <PromoCodeCard locale={locale} />

      <h2 className="text-tx-dim mb-3 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
        {t("historyTitle")}
      </h2>

      {history.isPending && <Skeleton className="h-24 rounded-2xl" />}
      {history.isError && <p className="text-sm text-red-400">{t("historyError")}</p>}

      {!history.isPending && !history.isError && rows.length === 0 && (
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

      {/* Keyed on what the server returned, not on what survived projection:
          a filtered-out row would otherwise hide the button early. */}
      {(history.data?.items.length ?? 0) >= limit && (
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

/** The line shown when an acquirer has just sent the customer back.
 *
 * Its own component so `useSearchParams` sits behind the Suspense boundary the
 * static export needs.
 */
function ReturnedFromAcquirer({ note }: { note: string }) {
  const justToppedUp = useSearchParams().get("topup") !== null;
  const qc = useQueryClient();

  // The ledger posts when the acquirer's webhook lands, which is seconds after
  // the customer is already looking at this page. Saying "the balance will
  // update" beside a figure that then never moves is worse than saying
  // nothing, so watch for it — briefly, and only on the trip back.
  useEffect(() => {
    if (!justToppedUp) return;
    const tick = setInterval(() => {
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    }, 5000);
    const stop = setTimeout(() => {
      clearInterval(tick);
    }, 60_000);
    return () => {
      clearInterval(tick);
      clearTimeout(stop);
    };
  }, [justToppedUp, qc]);

  if (!justToppedUp) return null;
  return (
    <p className="border-primary/30 bg-primary/10 text-tx-mute mb-4 rounded-2xl border p-4 text-sm leading-relaxed">
      {note}
    </p>
  );
}
