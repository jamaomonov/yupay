/** USDT reservations tab: number, reseller, exact amount, status badge and times. */

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Link } from "react-router-dom";

import { fetchReservations, formatUsdt, T, usdtErrorMessage, type UsdtReservation } from "./api";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState } from "@/components/States";
import { formatDateTime, labelOf } from "@/features/p2p/api";
import { qk } from "@/lib/queryKeys";

const R = T.reservations;

const TONES: Record<string, string | undefined> = {
  pending: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  paid: "bg-[var(--success-soft)] text-[var(--success-fg)]",
};
const MUTED = "bg-[var(--bg-muted)] text-[var(--text-secondary)]";

const columns: Column<UsdtReservation>[] = [
  { key: "number", header: R.number, render: (r) => r.number },
  {
    key: "merchant",
    header: R.merchant,
    render: (r) => (
      <Link to={`/merchants/${r.merchant_id}`} className="underline">
        {r.merchant_title ?? r.merchant_id}
      </Link>
    ),
  },
  { key: "amount", header: R.amount, render: (r) => formatUsdt(r.amount) },
  {
    key: "status",
    header: R.status,
    render: (r) => <Badge tone={TONES[r.status] ?? MUTED}>{labelOf(R.statuses, r.status)}</Badge>,
  },
  { key: "created", header: R.created, render: (r) => formatDateTime(r.created_at) },
  { key: "expires", header: R.expires, render: (r) => formatDateTime(r.expires_at) },
  { key: "closed", header: R.closed, render: (r) => formatDateTime(r.closed_at) },
];

export function UsdtReservations() {
  const q = useInfiniteQuery({
    queryKey: qk.usdtReservations(),
    queryFn: ({ pageParam }) => fetchReservations(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      {q.isError ? (
        <ErrorState description={usdtErrorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : null}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.number}
        loading={q.isLoading}
        empty={T.empty}
        ariaLabel={T.tabs.reservations}
        sortable={false}
      />
      {q.hasNextPage ? (
        <div className="mt-4">
          <Button
            variant="secondary"
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
          >
            {T.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
