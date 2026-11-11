/** USDT transfer journal: result filter (unmatched as a quick filter), cursor paging, resolve actions. */

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchIncoming,
  formatUsdt,
  shortHash,
  T,
  tronscanAddress,
  tronscanTx,
  usdtErrorMessage,
  type UsdtIncoming,
  type UsdtResult,
} from "./api";
import { UsdtResolvePanel, type ResolveAction } from "./UsdtResolvePanel";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState } from "@/components/States";
import { formatDateTime, labelOf } from "@/features/p2p/api";
import { qk } from "@/lib/queryKeys";

const J = T.journal;

const TONES: Record<UsdtResult, string> = {
  matched: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  manual: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  unmatched: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  ignored: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  dismissed: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
};

interface ChainLinkProps {
  href: string;
  value: string;
}

function ChainLink({ href, value }: ChainLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={value}
      className="font-mono text-xs underline"
    >
      {shortHash(value)}
    </a>
  );
}

function ResellerCell({ row }: { row: UsdtIncoming }) {
  if (!row.merchant_id && !row.reservation_number) return <>—</>;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {row.merchant_id ? (
        <Link to={`/merchants/${row.merchant_id}`} className="underline">
          {row.merchant_title ?? row.merchant_id}
        </Link>
      ) : null}
      {row.reservation_number ? (
        <span className="text-xs text-[var(--text-secondary)]">{row.reservation_number}</span>
      ) : null}
    </span>
  );
}

interface Resolving {
  row: UsdtIncoming;
  action: ResolveAction;
}

function buildColumns(onResolve: (r: Resolving) => void): Column<UsdtIncoming>[] {
  return [
    { key: "time", header: J.blockTime, render: (r) => formatDateTime(r.block_at) },
    { key: "amount", header: J.amount, render: (r) => formatUsdt(r.amount_usdt) },
    {
      key: "from",
      header: J.from,
      render: (r) => <ChainLink href={tronscanAddress(r.from_address)} value={r.from_address} />,
    },
    {
      key: "tx",
      header: J.tx,
      render: (r) => <ChainLink href={tronscanTx(r.tx_id)} value={r.tx_id} />,
    },
    {
      key: "result",
      header: J.result,
      render: (r) => <Badge tone={TONES[r.result]}>{labelOf(T.results, r.result)}</Badge>,
    },
    { key: "reseller", header: J.reseller, render: (r) => <ResellerCell row={r} /> },
    { key: "note", header: J.note, render: (r) => r.note ?? "—" },
    {
      key: "actions",
      header: J.actions,
      render: (r) =>
        r.result === "unmatched" ? (
          <span className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              onClick={() => {
                onResolve({ row: r, action: "credit" });
              }}
            >
              {J.credit}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                onResolve({ row: r, action: "dismiss" });
              }}
            >
              {J.dismiss}
            </Button>
          </span>
        ) : null,
    },
  ];
}

const RESULTS = Object.keys(T.results);

export function UsdtJournal() {
  const [result, setResult] = useState("");
  const [resolving, setResolving] = useState<Resolving | null>(null);

  const q = useInfiniteQuery({
    queryKey: qk.usdtIncoming(result),
    queryFn: ({ pageParam }) => fetchIncoming(result, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  const columns = buildColumns(setResolving);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Button
          variant={result === "unmatched" ? "primary" : "secondary"}
          aria-pressed={result === "unmatched"}
          onClick={() => {
            setResult(result === "unmatched" ? "" : "unmatched");
          }}
        >
          {T.filters.unmatched}
        </Button>
        <label className="text-sm">
          <span className="mb-1 block text-xs text-[var(--text-secondary)]">
            {T.filters.result}
          </span>
          <select
            className="h-9 rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
            value={result}
            onChange={(e) => {
              setResult(e.target.value);
            }}
          >
            <option value="">{T.filters.any}</option>
            {RESULTS.map((k) => (
              <option key={k} value={k}>
                {labelOf(T.results, k)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {resolving ? (
        <UsdtResolvePanel
          key={`${resolving.row.id}:${resolving.action}`}
          row={resolving.row}
          action={resolving.action}
          onClose={() => {
            setResolving(null);
          }}
        />
      ) : null}

      {q.isError ? (
        <ErrorState description={usdtErrorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : null}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.id}
        loading={q.isLoading}
        empty={T.empty}
        ariaLabel={T.tabs.journal}
        sortable={false}
        selectedKey={resolving?.row.id ?? null}
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
