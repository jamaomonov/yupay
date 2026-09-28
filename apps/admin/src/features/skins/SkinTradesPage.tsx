/**
 * CS2 skin trades — every skin purchase, newest first, with a tab for the ones a
 * human must settle (a rollback after delivery, a purchase Waxpeer never confirmed).
 * Row click opens the order. Tabs, search and page live in the URL.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, Loader } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  fetchTrades,
  fill,
  penaltyTotal,
  T,
  TRADES_PAGE_SIZE,
  unitsToUsd,
  type AdminSkinTradeOut,
  type TradesView,
} from "./api";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusChip } from "@/components/StatusChip";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

const VIEWS: ReadonlySet<TradesView> = new Set<TradesView>(["all", "active", "attention"]);
const PANEL_ID = "skin-trades-panel";

const when = (iso: string) =>
  new Intl.DateTimeFormat("ru", { dateStyle: "short", timeStyle: "short" }).format(new Date(iso));

function deadline(t: AdminSkinTradeOut): string {
  if (t.state === "offer_sent" && t.send_until)
    return fill(T.trades.acceptBy, { time: when(t.send_until) });
  if (t.state === "accepted" && t.release_date) {
    return fill(T.trades.protectedUntil, { date: when(t.release_date) });
  }
  return "—";
}

function why(t: AdminSkinTradeOut): string {
  const parts: string[] = [];
  if (t.task_sub_state) parts.push(T.trades.subState[t.task_sub_state]);
  if (t.reason) parts.push(t.reason);
  const penalty = penaltyTotal(t.penalties);
  if (penalty) parts.push(fill(T.trades.penalty, { amount: penalty }));
  return parts.length > 0 ? parts.join(" · ") : "—";
}

const COLUMNS: Column<AdminSkinTradeOut>[] = [
  { key: "created", header: T.trades.cols.created, render: (t) => when(t.created_at) },
  {
    key: "item",
    header: T.trades.cols.item,
    render: (t) => (
      <span className="inline-flex items-center gap-1.5">
        {t.attention && (
          <AlertTriangle
            size={14}
            className="text-[var(--danger)]"
            aria-label={T.trades.attention}
          />
        )}
        <span>{t.market_hash_name}</span>
        {t.phase && <span className="text-[var(--text-secondary)]">{t.phase}</span>}
      </span>
    ),
  },
  {
    key: "paid",
    header: T.trades.cols.paid,
    render: (t) => (
      <span className="tabular-nums">{unitsToUsd(t.bought_units ?? t.paid_units)}</span>
    ),
  },
  {
    key: "state",
    header: T.trades.cols.state,
    render: (t) => <StatusChip domain="skinTradeState" value={t.state} />,
  },
  { key: "seller", header: T.trades.cols.seller, render: (t) => t.seller_name ?? "—" },
  { key: "until", header: T.trades.cols.until, render: deadline },
  { key: "reason", header: T.trades.cols.reason, render: why },
];

export function SkinTradesPage() {
  const navigate = useNavigate();
  const [rawView] = useSearchParamsState("view", "all");
  const [, setParams] = useSearchParams();
  const view: TradesView = VIEWS.has(rawView as TradesView) ? (rawView as TradesView) : "all";
  const [query] = useSearchParamsState("q", "");
  const [offset, setOffset] = useSearchParamsState("offset", 0, numberCodec);

  // One URL write per change: two setters in one handler do not compose (react-router
  // reads the location once per call), so the tab/search and the page reset go together.
  const setFilter = (key: "view" | "q", value: string) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value && !(key === "view" && value === "all")) next.set(key, value);
        else next.delete(key);
        next.delete("offset");
        return next;
      },
      { replace: true },
    );
  };

  const trades = useQuery({
    queryKey: qk.skinTrades(view, query, offset),
    queryFn: () => fetchTrades(view, query, offset),
    refetchInterval: 15_000,
  });

  const tabs: TabDescriptor<TradesView>[] = [
    { id: "all", label: T.trades.tabs.all, icon: ListChecks, panelId: PANEL_ID },
    { id: "active", label: T.trades.tabs.active, icon: Loader, panelId: PANEL_ID },
    { id: "attention", label: T.trades.tabs.attention, icon: AlertTriangle, panelId: PANEL_ID },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title={T.trades.title} description={T.trades.description} />
      <Tabs<TradesView>
        value={view}
        onChange={(next) => {
          setFilter("view", next);
        }}
        tabs={tabs}
        ariaLabel={T.trades.title}
      />
      <input
        type="search"
        value={query}
        onChange={(e) => {
          setFilter("q", e.target.value);
        }}
        placeholder={T.trades.search}
        aria-label={T.trades.search}
        className="h-9 w-full max-w-sm rounded-md border border-[var(--border)] bg-transparent px-3 text-sm"
      />
      <div role="tabpanel" id={PANEL_ID} className="space-y-3">
        {trades.isError && <p className="text-sm text-[var(--danger)]">{T.trades.loadError}</p>}
        <DataTable
          rows={trades.data?.items ?? []}
          columns={COLUMNS}
          rowKey={(t) => t.id}
          loading={trades.isLoading}
          empty={T.trades.empty}
          ariaLabel={T.trades.title}
          onRowClick={(t) => {
            void navigate(`/orders/${t.order_id}`);
          }}
        />
        {(trades.data?.total ?? 0) > TRADES_PAGE_SIZE && (
          <Pagination
            total={trades.data?.total ?? 0}
            limit={TRADES_PAGE_SIZE}
            offset={offset}
            onPageChange={setOffset}
          />
        )}
      </div>
    </div>
  );
}
