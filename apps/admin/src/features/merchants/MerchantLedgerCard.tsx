import { useQuery } from "@tanstack/react-query";

import {
  T,
  fetchMerchantTxns,
  formatUsd,
  type MerchantTxnListOut,
  type MerchantTxnOut,
} from "./api";

import { DataTable, type Column } from "@/components/DataTable";
import { StatusChip } from "@/components/StatusChip";
import { qk } from "@/lib/queryKeys";

/**
 * Every movement of this merchant's deposit, newest first.
 *
 * Its own file because `MerchantDetail` had grown past the 500-line ceiling
 * AGENTS.md §6 sets once the page gained cards for keys, webhooks, operators
 * and pricing. The ledger is the cheapest thing to lift out — fifty lines of
 * column definitions and one read-only query, with no state shared with the
 * money forms above it.
 *
 * `description` is the operator's note on a manual movement (ADR-0087) and is
 * the only column that can be empty on purpose: everything the system posts
 * by itself explains itself through the order it names.
 */
export function MerchantLedgerCard({ merchantId }: { merchantId: string }) {
  const txnsQuery = useQuery<MerchantTxnListOut>({
    queryKey: qk.merchantTxns(merchantId),
    queryFn: () => fetchMerchantTxns(merchantId),
    enabled: Boolean(merchantId),
  });

  const columns: Column<MerchantTxnOut>[] = [
    {
      key: "created",
      header: T.ledger.columns.created,
      render: (t) => (
        <span className="text-[var(--text-secondary)]">
          {new Date(t.created_at).toLocaleString("ru")}
        </span>
      ),
      className: "w-40",
    },
    {
      key: "kind",
      header: T.ledger.columns.kind,
      render: (t) => <StatusChip domain="walletTxKind" value={t.kind} />,
    },
    {
      key: "amount",
      header: T.ledger.columns.amount,
      render: (t) => (
        <span
          className={`font-medium ${
            t.amount.startsWith("-") ? "text-[var(--danger-fg)]" : "text-[var(--success-fg)]"
          }`}
        >
          {t.amount.startsWith("-") ? "" : "+"}
          {formatUsd(t.amount)}
        </span>
      ),
      className: "w-32 text-right",
    },
    {
      key: "note",
      header: T.ledger.columns.note,
      render: (t) =>
        t.note ? <span>«{t.note}»</span> : <span className="text-[var(--text-secondary)]">—</span>,
    },
    {
      key: "actor",
      header: T.ledger.columns.actor,
      render: (t) =>
        t.actor ? (
          <span className="font-mono text-xs text-[var(--text-secondary)]">{t.actor}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        ),
      className: "w-44",
    },
  ];

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase text-[var(--text-secondary)]">
        {T.ledger.title}
      </h2>
      {txnsQuery.isError && <p className="text-sm text-[var(--danger)]">{T.ledger.loadError}</p>}
      <DataTable
        rows={txnsQuery.data?.items ?? []}
        columns={columns}
        rowKey={(t) => t.transaction_id}
        loading={txnsQuery.isLoading}
        empty={T.ledger.empty}
        ariaLabel={T.ledger.title}
        sortable={false}
      />
    </section>
  );
}
