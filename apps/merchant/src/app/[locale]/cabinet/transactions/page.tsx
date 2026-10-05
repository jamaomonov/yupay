"use client";

import { ArrowLeftRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { P2PDeposit, P2PDepositsPage, Transaction, TransactionsPage } from "@/lib/types";

import { BrandMark } from "@/components/BrandMark";
import { useCabinet } from "@/components/CabinetContext";
import { EmptyState } from "@/components/EmptyState";
import { ListSkeleton } from "@/components/ListSkeleton";
import { PageHeading } from "@/components/PageHeading";
import { api, downloadFile } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { transactionKindLabel } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";
import { formatSom } from "@/lib/p2p";

/**
 * The deposit statement.
 *
 * `amount_usd` is signed and the column adds up to the balance in the top
 * bar, so it is rendered with an explicit `+`/`−` rather than a colour alone —
 * the sign is the fact, and a colour is a hint about it.
 *
 * **«Баланс после» is computed here, not served.** The ledger reader has no
 * running balance, and the rows are newest-first and contiguous, so the
 * balance after row *n* is the current balance minus everything above it.
 * That holds across «показать ещё» because the pages are contiguous, and it
 * is off by exactly one order if a purchase lands in another tab between the
 * profile read and this one — which the next navigation corrects.
 */
/**
 * The balance immediately after row `index`, newest-first.
 *
 * Row 0 is the most recent movement, so the balance after it *is* the current
 * balance; each row below adds back what the rows above it moved.
 */
function runningBalance(balance: string | null, rows: Transaction[], index: number): bigint | null {
  if (balance === null) return null;
  let cents = toCents(balance);
  for (let above = 0; above < index; above += 1) {
    const row = rows[above];
    if (row === undefined) return null;
    cents -= toCents(row.amount_usd);
  }
  return cents;
}

/**
 * What a ledger row paid for: the order's brand mark and title, linked.
 *
 * A cabinet order's id is `manual-<digest>` — our mint, not the reseller's
 * reference — so printing it here read as a column of hashes. The title says
 * what the money bought; the id is shown only when it is the reseller's own.
 */
function OrderCell({ row, locale }: { row: Transaction; locale: string }) {
  if (row.merchant_order_id === null) {
    return row.description === null ? (
      <span className="text-tx-dim">—</span>
    ) : (
      <span className="text-tx-mute">{row.description}</span>
    );
  }
  const own = !row.merchant_order_id.startsWith("manual-");
  return (
    <Link
      href={pathFor(locale, `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`)}
      className="group flex min-w-0 items-center gap-2.5"
    >
      <BrandMark name={row.order_title} logoUrl={row.brand_logo_url ?? null} size="sm" />
      <span className="min-w-0">
        <span className="block truncate underline-offset-4 group-hover:underline">
          {row.order_title ?? row.merchant_order_id}
        </span>
        {own && row.order_title !== null && (
          <span className="text-tx-dim block truncate font-mono text-[11px]">
            {row.merchant_order_id}
          </span>
        )}
      </span>
    </Link>
  );
}

export default function TransactionsList() {
  const t = useTranslations("merchant.transactions");
  const tCommon = useTranslations("merchant.common");
  const { locale } = useParams<{ locale: string }>();
  const tTop = useTranslations("merchant.topUp");
  const { profile, p2p } = useCabinet();
  const [topUps, setTopUps] = useState<P2PDeposit[]>([]);
  const [rows, setRows] = useState<Transaction[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchPage = useCallback(async (after: string | null) => {
    setBusy(true);
    const query = after === null ? "" : `?cursor=${encodeURIComponent(after)}`;
    try {
      const page = await api<TransactionsPage>(`/transactions${query}`);
      setRows((previous) => (after === null ? page.items : [...(previous ?? []), ...page.items]));
      setCursor(page.next_cursor);
    } catch {
      // See the orders list: the reachable failures are a lapsed session and
      // a malformed cursor, neither of which this screen can produce.
      setRows([]);
      setCursor(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void fetchPage(null);
  }, [fetchPage]);

  const selfServe = p2p?.enabled === true;
  useEffect(() => {
    if (!selfServe) return;
    void api<P2PDepositsPage>("/p2p/deposits?limit=10")
      .then((page) => {
        setTopUps(page.items);
      })
      .catch(() => undefined);
  }, [selfServe]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeading icon={ArrowLeftRight} title={t("title")} />
        <button
          type="button"
          onClick={() => {
            void downloadFile("/transactions.csv").catch(() => undefined);
          }}
          className="border-border bg-card rounded-btn text-tx-mute border px-3 py-1.5 text-xs font-semibold"
        >
          {tCommon("exportCsv")}
        </button>
      </div>

      <section className="border-border bg-card mt-5 flex flex-wrap items-center gap-x-9 gap-y-3 rounded-xl border p-5">
        <div>
          <p className="text-tx-dim text-xs">{t("balance")}</p>
          <p className="text-primary-ink mt-0.5 font-mono text-2xl font-extrabold">
            {profile === null ? "—" : `$${formatUsd(toCents(profile.balance_usd))}`}
          </p>
        </div>
        {/* The hint said "write to support" with nothing to click, while the
            string for the link sat unused in all three locales. */}
        {/* Nothing until `/p2p/status` answers: the support hint used to flash
            for a moment before the top-up button replaced it. */}
        {p2p === null ? null : selfServe ? (
          <Link
            href={pathFor(locale, "/cabinet/top-up")}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2 text-sm font-semibold"
          >
            {tTop("title")}
          </Link>
        ) : (
          <p className="text-tx-dim max-w-md text-[12.5px] leading-relaxed">
            {t("topUpHint")}{" "}
            <a
              href="https://t.me/yupay_support"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              {t("requestDeposit")}
            </a>
          </p>
        )}
      </section>

      {topUps.length > 0 && (
        <section className="border-border bg-card mt-5 rounded-xl border p-5">
          <h2 className="text-tx-mute text-sm font-semibold">{tTop("history")}</h2>
          <ul className="divide-border mt-2 divide-y">
            {topUps.map((d) => (
              <li
                key={d.number}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
              >
                <span className="font-mono text-xs">{d.number}</span>
                <span className="font-mono">{formatSom(d.amount_uzs, locale)}</span>
                <span className="font-mono">${d.amount_usd}</span>
                <span className="text-tx-mute text-xs">{tTop(`status.${d.status}`)}</span>
                <span className="text-tx-dim text-xs">{formatMoment(d.created_at, locale)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {rows === null && <ListSkeleton className="mt-6" />}

      {rows !== null && rows.length === 0 && (
        <EmptyState icon={ArrowLeftRight} title={t("empty")} hint={t("emptyHint")} />
      )}

      {rows !== null && rows.length > 0 && (
        // One card per movement on a phone; the table cut the order column
        // mid-word and pushed the amount — the point of the row — off screen.
        <ul className="border-border bg-card divide-border mt-6 divide-y rounded-xl border md:hidden">
          {rows.map((row, index) => {
            const cents = toCents(row.amount_usd);
            const credit = cents >= 0n;
            const absolute = credit ? cents : -cents;
            const after = runningBalance(profile?.balance_usd ?? null, rows, index);
            return (
              <li key={row.transaction_id} className="px-4 py-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        credit ? "text-primary-ink bg-primary/10" : "text-tx-mute bg-tx-mute/10"
                      }`}
                    >
                      {transactionKindLabel(row.kind, t)}
                    </span>
                    <div className="mt-1.5 text-sm">
                      <OrderCell row={row} locale={locale} />
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`font-mono text-sm font-semibold ${credit ? "text-blue" : ""}`}>
                      {credit ? "+" : "−"}${formatUsd(absolute)}
                    </p>
                    <p className="text-tx-dim mt-1 font-mono text-[11px]">
                      {after === null ? "" : `$${formatUsd(after)}`}
                    </p>
                  </div>
                </div>
                <p className="text-tx-dim mt-1 text-xs">{formatMoment(row.created_at, locale)}</p>
              </li>
            );
          })}
        </ul>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="border-border bg-card mt-6 hidden overflow-x-auto rounded-xl border md:block">
          <table className="w-full min-w-[46rem] text-sm">
            <thead className="text-tx-dim border-border border-b text-left text-xs">
              <tr>
                <th className="px-4 py-3 font-medium">{t("colDate")}</th>
                <th className="px-4 py-3 font-medium">{t("colKind")}</th>
                <th className="px-4 py-3 font-medium">{t("colOrder")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("colAmount")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("colBalanceAfter")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const cents = toCents(row.amount_usd);
                const credit = cents >= 0n;
                const absolute = credit ? cents : -cents;
                const after = runningBalance(profile?.balance_usd ?? null, rows, index);
                return (
                  <tr key={row.transaction_id} className="border-border border-b last:border-0">
                    <td className="text-tx-mute whitespace-nowrap px-4 py-3">
                      {formatMoment(row.created_at, locale)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                          credit ? "text-primary-ink bg-primary/10" : "text-tx-mute bg-tx-mute/10"
                        }`}
                      >
                        {transactionKindLabel(row.kind, t)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {/* A manual movement has no order, so this cell was a
                          dash — and a debit reached the reseller as an
                          unexplained negative number against an account they
                          could only ask about by writing to us. The operator
                          already wrote the reason down; it just never left
                          the admin panel. */}
                      <OrderCell row={row} locale={locale} />
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-3 text-right font-mono ${
                        credit ? "text-blue" : ""
                      }`}
                    >
                      {credit ? "+" : "−"}${formatUsd(absolute)}
                    </td>
                    <td className="text-tx-mute whitespace-nowrap px-4 py-3 text-right font-mono">
                      {after === null ? "—" : `$${formatUsd(after)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {cursor !== null && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void fetchPage(cursor);
          }}
          className="border-border rounded-btn mt-5 border px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {t("loadMore")}
        </button>
      )}
    </div>
  );
}
