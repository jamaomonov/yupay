"use client";

import { ArrowLeftRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeading } from "@/components/PageHeading";
import type { Transaction, TransactionsPage } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { api, downloadFile } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { transactionKindLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

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

export default function TransactionsList() {
  const t = useTranslations("merchant.transactions");
  const { locale } = useParams<{ locale: string }>();
  const { profile } = useCabinet();
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
          {t("exportCsv")}
        </button>
      </div>

      <section className="border-border bg-card mt-5 flex flex-wrap items-center gap-x-9 gap-y-3 rounded-xl border p-5">
        <div>
          <p className="text-tx-dim text-xs">{t("balance")}</p>
          <p className="text-primary mt-0.5 font-mono text-2xl font-extrabold">
            {profile === null ? "—" : `$${formatUsd(toCents(profile.balance_usd))}`}
          </p>
        </div>
        <p className="text-tx-dim max-w-md text-[12.5px] leading-relaxed">{t("topUpHint")}</p>
      </section>

      {rows !== null && rows.length === 0 && (
        <EmptyState icon={ArrowLeftRight} title={t("empty")} />
      )}

      {rows !== null && rows.length > 0 && (
        <div className="border-border bg-card mt-6 overflow-x-auto rounded-xl border">
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
                          credit ? "text-primary bg-primary/10" : "text-tx-mute bg-tx-mute/10"
                        }`}
                      >
                        {transactionKindLabel(row.kind, t)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {row.merchant_order_id === null ? (
                        <span className="text-tx-dim">—</span>
                      ) : (
                        <Link
                          href={`/${locale}/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {row.merchant_order_id}
                        </Link>
                      )}
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
