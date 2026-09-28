/**
 * CS2 skin trades — every skin purchase, newest first, with tabs counting what is in
 * flight and what a human must settle (a rollback after delivery, a purchase Waxpeer
 * never confirmed). A row opens the trade's details; phones get cards instead of a
 * table. Tab, search and page live in the URL.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, Loader } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  boughtUsd,
  fetchTrades,
  fill,
  marginText,
  reasonText,
  shortWhen,
  T,
  TRADES_PAGE_SIZE,
  usd,
  type AdminSkinTradeOut,
  type TradesView,
} from "./api";
import { TradeDrawer } from "./TradeDrawer";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusChip } from "@/components/StatusChip";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

const VIEWS: ReadonlySet<TradesView> = new Set<TradesView>(["all", "active", "attention"]);
const PANEL_ID = "skin-trades-panel";
const SEARCH_DEBOUNCE_MS = 300;
const ATTENTION_ROW = "!bg-[var(--danger-soft)]";

function deadline(t: AdminSkinTradeOut): string | null {
  if (t.state === "offer_sent" && t.send_until) {
    return fill(T.trades.acceptBy, { time: shortWhen(t.send_until) });
  }
  if (t.state === "accepted" && t.release_date) {
    return fill(T.trades.protectedUntil, { date: shortWhen(t.release_date) });
  }
  return null;
}

function SkinName({ t }: { t: AdminSkinTradeOut }) {
  return (
    <span className="flex min-w-0 max-w-[16rem] items-center gap-2">
      {t.image_url ? (
        <img src={t.image_url} alt="" className="h-8 w-11 shrink-0 object-contain" />
      ) : (
        <span className="h-8 w-11 shrink-0 rounded bg-[var(--bg-muted)]" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="block truncate">{t.market_hash_name}</span>
        {t.phase && <span className="block text-xs text-[var(--text-secondary)]">{t.phase}</span>}
      </span>
    </span>
  );
}

const COLUMNS: Column<AdminSkinTradeOut>[] = [
  {
    key: "created",
    header: T.trades.cols.created,
    className: "whitespace-nowrap",
    render: (t) => shortWhen(t.created_at),
  },
  { key: "item", header: T.trades.cols.item, render: (t) => <SkinName t={t} /> },
  {
    key: "paid",
    header: T.trades.cols.paid,
    className: "whitespace-nowrap tabular-nums",
    render: (t) => usd(boughtUsd(t)),
  },
  {
    key: "margin",
    header: T.trades.cols.margin,
    className: "whitespace-nowrap tabular-nums",
    render: marginText,
  },
  {
    key: "state",
    header: T.trades.cols.state,
    render: (t) => (
      <span className="flex flex-col items-start gap-1">
        <StatusChip domain="skinTradeState" value={t.state} />
        {deadline(t) && <span className="text-xs text-[var(--text-secondary)]">{deadline(t)}</span>}
      </span>
    ),
  },
  { key: "seller", header: T.trades.cols.seller, render: (t) => t.seller_name ?? "—" },
  {
    key: "reason",
    header: T.trades.cols.reason,
    className: "min-w-[12rem]",
    render: (t) =>
      t.resolved_at ? (
        <span className="text-xs text-[var(--text-secondary)]">
          {fill(T.trades.resolvedOn, { date: shortWhen(t.resolved_at) })}
        </span>
      ) : (
        <span className={t.attention ? "font-medium text-[var(--danger)]" : ""}>
          {reasonText(t) ?? "—"}
        </span>
      ),
  },
];

/** Phones: one card per trade — the table would hide everything past the price. */
function TradeCards({
  rows,
  onOpen,
}: {
  rows: AdminSkinTradeOut[];
  onOpen: (t: AdminSkinTradeOut) => void;
}) {
  return (
    <ul className="space-y-2 md:hidden" aria-label={T.trades.title}>
      {rows.map((t) => (
        <li key={t.id}>
          <button
            type="button"
            onClick={() => {
              onOpen(t);
            }}
            className={`w-full space-y-2 rounded-lg border border-[var(--border-default)] p-3 text-left text-sm ${
              t.attention ? "bg-[var(--danger-soft)]" : "bg-[var(--bg-surface)]"
            }`}
          >
            <SkinName t={t} />
            <span className="flex flex-wrap items-center gap-2">
              <StatusChip domain="skinTradeState" value={t.state} />
              <span className="tabular-nums">{usd(boughtUsd(t))}</span>
              <span className="text-xs text-[var(--text-secondary)]">
                {shortWhen(t.created_at)}
              </span>
            </span>
            {deadline(t) && <span className="block text-xs">{deadline(t)}</span>}
            {(reasonText(t) ?? t.resolved_at) && (
              <span
                className={`block text-xs ${t.attention ? "font-medium text-[var(--danger)]" : "text-[var(--text-secondary)]"}`}
              >
                {t.resolved_at
                  ? fill(T.trades.resolvedOn, { date: shortWhen(t.resolved_at) })
                  : reasonText(t)}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function SkinTradesPage() {
  const [rawView] = useSearchParamsState("view", "all");
  const view: TradesView = VIEWS.has(rawView as TradesView) ? (rawView as TradesView) : "all";
  const [query] = useSearchParamsState("q", "");
  const [, setParams] = useSearchParams();
  const [offset, setOffset] = useSearchParamsState("offset", 0, numberCodec);
  // What is in the box; the URL (and the request) follows once typing pauses.
  const [typed, setTyped] = useState(query);
  const [open, setOpen] = useState<AdminSkinTradeOut | null>(null);

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

  useEffect(() => {
    if (typed === query) return;
    const timer = setTimeout(() => {
      setFilter("q", typed);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
    // `setFilter` is recreated each render; the typed text is what re-arms the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed, query]);

  const trades = useQuery({
    queryKey: qk.skinTrades(view, query, offset),
    queryFn: () => fetchTrades(view, query, offset),
    refetchInterval: 15_000,
  });
  const counts = trades.data?.counts;
  const rows = trades.data?.items ?? [];

  const tabs: TabDescriptor<TradesView>[] = [
    { id: "all", label: T.trades.tabs.all, icon: ListChecks, panelId: PANEL_ID },
    {
      id: "active",
      label: T.trades.tabs.active,
      icon: Loader,
      badge: { count: counts?.active ?? 0, tone: "muted" },
      panelId: PANEL_ID,
    },
    {
      id: "attention",
      label: T.trades.tabs.attention,
      icon: AlertTriangle,
      badge: { count: counts?.attention ?? 0, tone: "warn" },
      panelId: PANEL_ID,
    },
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
        value={typed}
        onChange={(e) => {
          setTyped(e.target.value);
        }}
        placeholder={T.trades.search}
        aria-label={T.trades.search}
        className="h-9 w-full max-w-sm rounded-md border border-[var(--border)] bg-transparent px-3 text-sm"
      />
      <div role="tabpanel" id={PANEL_ID} className="space-y-3">
        {trades.isError && <p className="text-sm text-[var(--danger)]">{T.trades.loadError}</p>}
        <TradeCards rows={rows} onOpen={setOpen} />
        <div className="hidden md:block">
          <DataTable
            rows={rows}
            columns={COLUMNS}
            rowKey={(t) => t.id}
            loading={trades.isLoading}
            empty={T.trades.empty}
            ariaLabel={T.trades.title}
            onRowClick={setOpen}
            selectedKey={open?.id ?? null}
            rowClassName={(t) => (t.attention ? ATTENTION_ROW : "")}
          />
        </div>
        {(trades.data?.total ?? 0) > TRADES_PAGE_SIZE && (
          <Pagination
            total={trades.data?.total ?? 0}
            limit={TRADES_PAGE_SIZE}
            offset={offset}
            onPageChange={setOffset}
          />
        )}
      </div>
      {open && (
        <TradeDrawer
          trade={open}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </div>
  );
}
