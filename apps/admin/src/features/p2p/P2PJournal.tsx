/** Incoming-transfers journal: filters, cursor paging and a raw-text detail panel. */

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  labelOf,
  fetchIncoming,
  fetchIncomingDetail,
  formatDateTime,
  formatUzs,
  p2pErrorMessage,
  T,
  type JournalFilters,
  type P2PIncoming,
} from "./api";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, Spinner } from "@/components/States";
import { qk } from "@/lib/queryKeys";

const EMPTY: JournalFilters = { card_last4: "", kind: "", result: "", amount: "" };
const TX = T.transfers;

function ResultCell({ row }: { row: P2PIncoming }) {
  const label = labelOf(TX.results, row.result);
  const res = row.reservation;
  if (row.result === "matched" && res) {
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        <Badge tone="bg-[var(--success-soft)] text-[var(--success-fg)]">{label}</Badge>
        {res.merchant_id ? (
          <Link
            to={`/merchants/${res.merchant_id}`}
            className="underline"
            onClick={(e) => {
              e.stopPropagation();
            }}
          >
            {res.merchant_title ?? res.merchant_id}
          </Link>
        ) : null}
        <span className="text-xs text-[var(--text-secondary)]">{res.number}</span>
      </span>
    );
  }
  const tone =
    row.result === "unmatched"
      ? "bg-[var(--warning-soft)] text-[var(--warning-fg)]"
      : "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
  return <Badge tone={tone}>{label}</Badge>;
}

const columns: Column<P2PIncoming>[] = [
  {
    key: "time",
    header: TX.journal.bankTime,
    render: (r) => formatDateTime(r.bank_time ?? r.received_at),
  },
  { key: "amount", header: TX.journal.amount, render: (r) => formatUzs(r.amount_uzs) },
  { key: "source", header: TX.journal.source, render: (r) => r.source_text ?? "—" },
  {
    key: "card",
    header: TX.journal.card,
    render: (r) => (r.card_last4 ? `*${r.card_last4}` : "—"),
  },
  {
    key: "balance",
    header: TX.journal.balance,
    render: (r) => (
      <span className="flex items-center gap-1.5">
        {formatUzs(r.balance_after)}
        {r.chain_ok === false ? (
          <Badge tone="bg-[var(--danger-soft)] text-[var(--danger-fg)]">
            {TX.journal.chainBroken}
          </Badge>
        ) : null}
      </span>
    ),
  },
  {
    key: "kind",
    header: TX.journal.kind,
    render: (r) => labelOf(TX.kinds, r.kind),
  },
  { key: "result", header: TX.journal.result, render: (r) => <ResultCell row={r} /> },
];

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Record<string, string>;
  onChange: (v: string) => void;
}) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-xs text-[var(--text-secondary)]">{label}</span>
      <select
        className="h-9 rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      >
        <option value="">{TX.filters.any}</option>
        {Object.entries(options).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}

function DetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({
    queryKey: qk.p2pIncomingDetail(id),
    queryFn: () => fetchIncomingDetail(id),
  });
  return (
    <aside
      className="mb-4 rounded-lg border bg-[var(--bg-surface)] p-4"
      aria-label={TX.detail.title}
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-medium">{TX.detail.title}</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {TX.detail.close}
        </Button>
      </div>
      {q.isLoading ? <Spinner label={T.loading} /> : null}
      {q.isError ? (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {TX.detail.loadError}
        </p>
      ) : null}
      {q.data ? (
        <>
          <p className="mb-1 text-xs text-[var(--text-secondary)]">{TX.detail.raw}</p>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-[var(--bg-muted)] p-2 text-xs">
            {q.data.raw_text}
          </pre>
        </>
      ) : null}
    </aside>
  );
}

export function P2PJournal() {
  const [draft, setDraft] = useState<JournalFilters>(EMPTY);
  const [filters, setFilters] = useState<JournalFilters>(EMPTY);
  const [openId, setOpenId] = useState<string | null>(null);

  const q = useInfiniteQuery({
    queryKey: qk.p2pIncoming(filters),
    queryFn: ({ pageParam }) => fetchIncoming(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  const set = (k: keyof JournalFilters) => (v: string) => {
    setDraft((d) => ({ ...d, [k]: v }));
  };

  return (
    <div>
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <label className="text-sm">
          <span className="mb-1 block text-xs text-[var(--text-secondary)]">{TX.filters.card}</span>
          <Input
            className="w-24"
            maxLength={4}
            inputMode="numeric"
            value={draft.card_last4}
            onChange={(e) => {
              set("card_last4")(e.target.value);
            }}
          />
        </label>
        <Select
          label={TX.filters.kind}
          value={draft.kind}
          options={TX.kinds}
          onChange={(v) => {
            set("kind")(v);
            setFilters({ ...draft, kind: v });
          }}
        />
        <Select
          label={TX.filters.result}
          value={draft.result}
          options={TX.results}
          onChange={(v) => {
            set("result")(v);
            setFilters({ ...draft, result: v });
          }}
        />
        <label className="text-sm">
          <span className="mb-1 block text-xs text-[var(--text-secondary)]">
            {TX.filters.amount}
          </span>
          <Input
            className="w-36"
            inputMode="decimal"
            value={draft.amount}
            onChange={(e) => {
              set("amount")(e.target.value);
            }}
          />
        </label>
        <Button type="submit" variant="secondary">
          {TX.filters.apply}
        </Button>
      </form>

      {openId ? (
        <DetailPanel
          key={openId}
          id={openId}
          onClose={() => {
            setOpenId(null);
          }}
        />
      ) : null}

      {q.isError ? (
        <ErrorState description={p2pErrorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : null}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.id}
        loading={q.isLoading}
        empty={TX.empty}
        ariaLabel={TX.tabs.journal}
        sortable={false}
        selectedKey={openId}
        onRowClick={(r) => {
          setOpenId(r.id);
        }}
      />
      {q.hasNextPage ? (
        <div className="mt-4">
          <Button
            variant="secondary"
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
          >
            {TX.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
