/** Reservations tab: number, merchant, card, amounts, status and times. */

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchReservations,
  labelOf,
  formatDateTime,
  formatUzs,
  p2pErrorMessage,
  T,
  type P2PReservation,
} from "./api";

import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState } from "@/components/States";
import { qk } from "@/lib/queryKeys";

const R = T.transfers.reservations;

const columns: Column<P2PReservation>[] = [
  { key: "number", header: R.number, render: (r) => r.number },
  {
    key: "merchant",
    header: R.merchant,
    render: (r) =>
      r.merchant_id ? (
        <Link to={`/merchants/${r.merchant_id}`} className="underline">
          {r.merchant_title ?? r.merchant_id}
        </Link>
      ) : (
        "—"
      ),
  },
  { key: "card", header: R.card, render: (r) => `*${r.card_last4}` },
  { key: "uzs", header: R.uzs, render: (r) => formatUzs(r.amount_uzs) },
  { key: "usd", header: R.usd, render: (r) => r.amount_usd },
  {
    key: "status",
    header: R.status,
    render: (r) => labelOf(R.statuses, r.status),
  },
  { key: "created", header: R.created, render: (r) => formatDateTime(r.created_at) },
  { key: "expires", header: R.expires, render: (r) => formatDateTime(r.expires_at) },
  { key: "closed", header: R.closed, render: (r) => formatDateTime(r.closed_at) },
];

export function P2PReservations() {
  const [status, setStatus] = useState("");
  const q = useInfiniteQuery({
    queryKey: qk.p2pReservations(status),
    queryFn: ({ pageParam }) => fetchReservations(status, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <label className="mb-4 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">
          {T.transfers.filters.status}
        </span>
        <select
          className="h-9 rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
          }}
        >
          <option value="">{T.transfers.filters.any}</option>
          {Object.entries(R.statuses).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      {q.isError ? (
        <ErrorState description={p2pErrorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : null}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.number}
        loading={q.isLoading}
        empty={T.transfers.empty}
        ariaLabel={T.transfers.tabs.reservations}
        sortable={false}
      />
      {q.hasNextPage ? (
        <div className="mt-4">
          <Button
            variant="secondary"
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
          >
            {T.transfers.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
