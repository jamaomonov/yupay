import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Ban, Search } from "lucide-react";
import { useCallback, useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  type OrderAdminListOut,
  type OrderAdminOut,
  type OrderStatus,
  STATUS_LABEL,
  STATUS_TONE,
} from "./types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

const PAGE_SIZE = 50;

const STATUS_FILTERS: { value: OrderStatus | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending_payment", label: "Ждёт оплаты" },
  { value: "paid", label: "Оплачен" },
  { value: "fulfilling", label: "В работе" },
  { value: "fulfilled", label: "Готов" },
  { value: "delivered", label: "Доставлен" },
  { value: "cancelled", label: "Отменён" },
  { value: "expired", label: "Истёк" },
  { value: "refunded", label: "Возврат" },
];

export function OrdersListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  // Filters live in the URL so the view is shareable and survives reload (ADR-0017).
  // `status`/`dateFrom`/`dateTo` are read through `useSearchParamsState` (always
  // fresh from the current render's URL) but *written* through `applyFilters`
  // below instead of their individual setters — `setSearchParams` computes its
  // next value from the params snapshot closed over at the *previous* render,
  // so firing two of these setters back-to-back in one handler (e.g. "change
  // status" + "reset the page to 0") makes the second call silently clobber
  // the first with a stale snapshot. `offset` alone still uses its own setter
  // since paging never touches another filter in the same handler.
  const [status] = useSearchParamsState<OrderStatus | "">("status", "");
  const [query, setQuery] = useSearchParamsState("q", "");
  const [offset, setOffset] = useSearchParamsState("offset", 0, numberCodec);
  // Plain `YYYY-MM-DD` from <input type="date">; converted to ISO
  // day-boundary instants before hitting the API (see `toSinceIso`/`toUntilIso`).
  const [dateFrom] = useSearchParamsState("from", "");
  const [dateTo] = useSearchParamsState("to", "");
  const [, setSearchParams] = useSearchParams();

  // Atomically applies one or more filter changes and resets pagination back
  // to page 0 in a single URL update — see the comment above for why this
  // can't be three separate `useSearchParamsState` setter calls.
  const applyFilters = useCallback(
    (patch: Partial<{ status: string; from: string; to: string }>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(patch)) {
            if (value) next.set(key, value);
            else next.delete(key);
          }
          next.delete("offset");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const ordersQuery = useQuery<OrderAdminListOut>({
    queryKey: [
      ...qk.orders({ status: status || null }),
      "page",
      offset,
      dateFrom || null,
      dateTo || null,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status_filter", status);
      const since = toSinceIso(dateFrom);
      if (since) params.set("since", since);
      const until = toUntilIso(dateTo);
      if (until) params.set("until", until);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<OrderAdminListOut>(`/api/v1/admin/orders?${params.toString()}`);
    },
    refetchInterval: 10_000,
  });

  const cancel = useMutation<OrderAdminOut, ApiError, OrderAdminOut>({
    mutationFn: (o) => apiPost<OrderAdminOut>(`/api/v1/admin/orders/${o.id}/cancel`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
    },
  });

  const rows = ordersQuery.data?.items ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (o) =>
        o.id.toLowerCase().includes(q) ||
        (o.user_id ?? "").toLowerCase().includes(q) ||
        (o.guest_email ?? "").toLowerCase().includes(q),
    );
  }, [rows, query]);

  const counters = useMemo(() => {
    const c: Partial<Record<OrderStatus, number>> = {};
    for (const o of rows) c[o.status] = (c[o.status] ?? 0) + 1;
    return c;
  }, [rows]);

  const totalCharged = useMemo(
    () =>
      rows.reduce<Record<string, number>>((acc, o) => {
        const key = o.currency;
        const v = Number.parseFloat(o.total_charged) || 0;
        acc[key] = (acc[key] ?? 0) + v;
        return acc;
      }, {}),
    [rows],
  );

  const columns: Column<OrderAdminOut>[] = [
    {
      key: "id",
      header: "ID / актёр",
      render: (o) => (
        <div className="flex flex-col font-mono text-xs">
          <span>{o.id.slice(0, 8)}…</span>
          {o.user_id ? (
            <Link
              to={`/customers/${o.user_id}`}
              onClick={(e) => {
                e.stopPropagation();
              }}
              className="text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
            >
              user {o.user_id.slice(0, 8)}…
            </Link>
          ) : (
            <span className="text-[var(--text-secondary)]">{o.guest_email ?? "—"}</span>
          )}
        </div>
      ),
    },
    {
      key: "items",
      header: "Товар",
      render: (o) => {
        const first = o.items[0]?.display ?? null;
        if (!first) {
          return (
            <span className="text-xs text-[var(--text-secondary)]">{o.items.length} поз.</span>
          );
        }
        const extra = o.items.length - 1;
        const headline = first.brand_name
          ? `${first.brand_name} · ${first.denomination ?? first.sku_code}`
          : `${first.product_name || first.product_slug} · ${first.denomination ?? first.sku_code}`;
        return (
          <div className="flex min-w-0 items-center gap-2">
            {first.image_url ? (
              <img
                src={first.image_url}
                alt=""
                className="size-7 flex-shrink-0 rounded border border-[var(--border-default)] object-cover"
              />
            ) : (
              <div
                className="flex size-7 flex-shrink-0 items-center justify-center rounded border border-[var(--border-default)] text-[10px] font-bold text-[var(--text-secondary)]"
                style={{ background: "var(--bg-muted)" }}
              >
                {(first.brand_name?.[0] ?? "?").toUpperCase()}
              </div>
            )}
            <div className="min-w-0">
              <div className="truncate text-sm">{headline}</div>
              {extra > 0 && (
                <div className="text-[10px] text-[var(--text-secondary)]">+{extra} ещё</div>
              )}
            </div>
          </div>
        );
      },
    },
    {
      key: "total",
      header: "Сумма",
      render: (o) => (
        <span className="font-medium">{formatMoney(o.total_charged, o.currency)}</span>
      ),
      className: "w-32 text-right",
      sortAccessor: (o) => Number.parseFloat(o.total_charged) || 0,
    },
    {
      key: "status",
      header: "Статус",
      render: (o) => <StatusBadge status={o.status} />,
      className: "w-40",
      sortAccessor: (o) => o.status,
    },
    {
      key: "created",
      header: "Создан",
      render: (o) => formatDate(o.created_at),
      className: "w-36",
      sortAccessor: (o) => new Date(o.created_at),
    },
    {
      key: "delivered",
      header: "Доставлен",
      render: (o) => formatDate(o.delivered_at),
      className: "w-36",
    },
    {
      key: "actions",
      header: "",
      render: (o) => (
        <div
          className="flex justify-end gap-1"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          {o.status === "pending_payment" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm(`Отменить заказ ${o.id.slice(0, 8)}?`)) {
                  cancel.mutate(o);
                }
              }}
              disabled={cancel.isPending}
              aria-label="Отменить"
            >
              <Ban className="size-4 text-[var(--danger)]" />
            </Button>
          )}
        </div>
      ),
      className: "w-20 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Заказы"
        description="Полный жизненный цикл: оплата → фулфилмент → доставка."
        actions={<SaveSegmentButton />}
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Всего" value={rows.length} accent />
        <StatCard
          label="Ждут оплаты"
          value={counters.pending_payment ?? 0}
          tone={counters.pending_payment ? "warn" : "muted"}
        />
        <StatCard label="В работе" value={(counters.paid ?? 0) + (counters.fulfilling ?? 0)} />
        <StatCard label="Доставлено" value={counters.delivered ?? 0} />
      </section>

      <section className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="relative md:col-span-2">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]" />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            placeholder="Поиск по order_id / user_id / email…"
            className="pl-9"
          />
        </div>
        <select
          value={status}
          onChange={(e) => {
            applyFilters({ status: e.target.value });
          }}
          className="h-10 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </section>

      <section className="mb-5 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          Создан с
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => {
              applyFilters({ from: e.target.value });
            }}
            className="h-9 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm text-[var(--text-primary)]"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          по
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => {
              applyFilters({ to: e.target.value });
            }}
            className="h-9 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm text-[var(--text-primary)]"
          />
        </label>
        {(dateFrom || dateTo) && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              applyFilters({ from: "", to: "" });
            }}
          >
            Сбросить даты
          </Button>
        )}
      </section>

      {/* The Input setter is wired to the local search-param state; the controlled `query`
          string also flows back through the URL so admins can share their working view. */}

      {Object.keys(totalCharged).length > 0 && (
        <p className="mb-3 text-xs text-[var(--text-secondary)]">
          Сумма по списку:{" "}
          {Object.entries(totalCharged)
            .map(([cur, v]) => formatMoney(v, cur))
            .join(" · ")}
        </p>
      )}

      {ordersQuery.isError && <p className="text-sm text-[var(--danger)]">Не удалось загрузить.</p>}

      <DataTable
        rows={filtered}
        columns={columns}
        rowKey={(o) => o.id}
        loading={ordersQuery.isPending}
        onRowClick={(o) => navigate(`/orders/${o.id}`)}
        empty={status || query ? "Под фильтр / поиск ничего не подошло." : "Заказов пока нет."}
      />

      <Pagination
        total={ordersQuery.data?.total ?? 0}
        limit={PAGE_SIZE}
        offset={offset}
        onPageChange={setOffset}
      />
    </div>
  );
}

function StatusBadge({ status }: { status: OrderStatus }) {
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

function StatCard({
  label,
  value,
  accent,
  tone = "default",
}: {
  label: string;
  value: number;
  accent?: boolean;
  tone?: "default" | "warn" | "muted";
}) {
  const valueCls = accent
    ? "text-[var(--accent)]"
    : tone === "warn"
      ? "text-[var(--danger)]"
      : "text-[var(--text-primary)]";
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <div className={`text-2xl font-semibold ${valueCls}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">{label}</div>
    </div>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// `<input type="date">` yields a local-timezone `YYYY-MM-DD` string with no
// time component. The admin API's `since`/`until` are inclusive bounds on
// `created_at`, so "from" is the start of that local day and "to" is the end
// of it — otherwise picking the same day for both would match zero orders.
function toSinceIso(dateOnly: string): string | null {
  if (!dateOnly) return null;
  const d = new Date(`${dateOnly}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function toUntilIso(dateOnly: string): string | null {
  if (!dateOnly) return null;
  const d = new Date(`${dateOnly}T23:59:59.999`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
