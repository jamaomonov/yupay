import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Ban, Search } from "lucide-react";

import { Button, Input } from "@yupay/ui";
import { Spinner } from "@/components/States";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { Pagination } from "@/components/Pagination";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";

const PAGE_SIZE = 50;

import {
  type OrderAdminListOut,
  type OrderAdminOut,
  type OrderStatus,
  STATUS_LABEL,
  STATUS_TONE,
} from "./types";

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
  const [status, setStatus] = useSearchParamsState<OrderStatus | "">("status", "");
  const [query, setQuery] = useSearchParamsState("q", "");
  const [offset, setOffset] = useSearchParamsState("offset", 0, numberCodec);

  const ordersQuery = useQuery<OrderAdminListOut>({
    queryKey: [
      ...qk.orders({ status: status || null }),
      "page",
      offset,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status_filter", status);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<OrderAdminListOut>(
        `/api/v1/admin/orders?${params.toString()}`,
      );
    },
    refetchInterval: 10_000,
  });

  const cancel = useMutation<OrderAdminOut, ApiError, OrderAdminOut>({
    mutationFn: (o) =>
      apiPost<OrderAdminOut>(`/api/v1/admin/orders/${o.id}/cancel`, {}),
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
      rows.reduce(
        (acc, o) => {
          const key = o.currency;
          const v = Number.parseFloat(o.total_charged) || 0;
          acc[key] = (acc[key] ?? 0) + v;
          return acc;
        },
        {} as Record<string, number>,
      ),
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
              onClick={(e) => { e.stopPropagation(); }}
              className="text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
            >
              user {o.user_id.slice(0, 8)}…
            </Link>
          ) : (
            <span className="text-[var(--text-secondary)]">
              {o.guest_email ?? "—"}
            </span>
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
            <span className="text-xs text-[var(--text-secondary)]">
              {o.items.length} поз.
            </span>
          );
        }
        const extra = o.items.length - 1;
        const headline = first.brand_name
          ? `${first.brand_name} · ${first.denomination ?? first.sku_code}`
          : `${first.product_name || first.product_slug} · ${first.denomination ?? first.sku_code}`;
        return (
          <div className="flex items-center gap-2 min-w-0">
            {first.image_url ? (
              <img
                src={first.image_url}
                alt=""
                className="size-7 rounded object-cover border border-[var(--border-default)] flex-shrink-0"
              />
            ) : (
              <div
                className="size-7 rounded flex items-center justify-center text-[10px] font-bold text-[var(--text-secondary)] border border-[var(--border-default)] flex-shrink-0"
                style={{ background: "var(--bg-muted)" }}
              >
                {(first.brand_name?.[0] ?? "?").toUpperCase()}
              </div>
            )}
            <div className="min-w-0">
              <div className="truncate text-sm">{headline}</div>
              {extra > 0 && (
                <div className="text-[10px] text-[var(--text-secondary)]">
                  +{extra} ещё
                </div>
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
        <span className="font-medium">
          {Number.parseFloat(o.total_charged).toFixed(2)} {o.currency}
        </span>
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
          onClick={(e) => e.stopPropagation()}
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
        <StatCard
          label="В работе"
          value={(counters.paid ?? 0) + (counters.fulfilling ?? 0)}
        />
        <StatCard label="Доставлено" value={counters.delivered ?? 0} />
      </section>

      <section className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="md:col-span-2 relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]" />
          <Input
            value={query}
            onChange={(e) => { setQuery(e.target.value); }}
            placeholder="Поиск по order_id / user_id / email…"
            className="pl-9"
          />
        </div>
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as OrderStatus | "");
            setOffset(0);
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

      {/* The Input setter is wired to the local search-param state; the controlled `query`
          string also flows back through the URL so admins can share their working view. */}

      {Object.keys(totalCharged).length > 0 && (
        <p className="mb-3 text-xs text-[var(--text-secondary)]">
          Сумма по списку:{" "}
          {Object.entries(totalCharged)
            .map(
              ([cur, v]) => `${v.toFixed(2)} ${cur}`,
            )
            .join(" · ")}
        </p>
      )}

      {ordersQuery.isLoading && (
        <Spinner label="Загрузка…" />
      )}
      {ordersQuery.isError && (
        <p className="text-sm text-[var(--danger)]">Не удалось загрузить.</p>
      )}

      <DataTable
        rows={filtered}
        columns={columns}
        rowKey={(o) => o.id}
        onRowClick={(o) => navigate(`/orders/${o.id}`)}
        empty={
          status || query
            ? "Под фильтр / поиск ничего не подошло."
            : "Заказов пока нет."
        }
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
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
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
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
      <div className={`text-2xl font-semibold ${valueCls}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </div>
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
