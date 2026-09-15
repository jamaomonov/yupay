"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { Transaction, TransactionsPage } from "@/lib/types";

import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { transactionKindLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

/**
 * The deposit statement.
 *
 * `amount_usd` is signed and the column adds up to the balance on the
 * dashboard, so it is rendered with an explicit `+`/`−` rather than a colour
 * alone — the sign is the fact, and a colour is a hint about it.
 */
export default function TransactionsList() {
  const t = useTranslations("merchant.transactions");
  const { locale } = useParams<{ locale: string }>();
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
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>

      {rows !== null && rows.length === 0 && (
        <p className="text-tx-dim mt-8 text-sm">{t("empty")}</p>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="border-border bg-card mt-6 overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[38rem] text-sm">
            <thead className="text-tx-dim border-border border-b text-left text-xs">
              <tr>
                <th className="px-4 py-3 font-medium">{t("colDate")}</th>
                <th className="px-4 py-3 font-medium">{t("colKind")}</th>
                <th className="px-4 py-3 font-medium">{t("colOrder")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("colAmount")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const cents = toCents(row.amount_usd);
                const credit = cents >= 0n;
                const absolute = credit ? cents : -cents;
                return (
                  <tr key={row.transaction_id} className="border-border border-b last:border-0">
                    <td className="text-tx-mute whitespace-nowrap px-4 py-3">
                      {formatMoment(row.created_at, locale)}
                    </td>
                    <td className="px-4 py-3">{transactionKindLabel(row.kind, t)}</td>
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
