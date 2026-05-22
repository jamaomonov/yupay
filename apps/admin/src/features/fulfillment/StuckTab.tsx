/**
 * Stuck tab — tasks in_progress longer than the SLA threshold.
 *
 * The "stuck" status is computed client-side from ``created_at`` because the
 * existing /admin/fulfillment/tasks endpoint doesn't filter by age. A task
 * that legitimately stays in_progress (manual queue) shows up here once it
 * crosses 30 min, which is intentional — the operator should pick it up.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type { TaskAdminOut, TaskListOut } from "./types";

const STUCK_AFTER_MS = 30 * 60_000;

export function StuckTab() {
  const navigate = useNavigate();
  const query = useQuery<TaskListOut>({
    queryKey: [...qk.fulfillmentTasks({ status: "in_progress" }), "stuck"],
    queryFn: () =>
      apiGet<TaskListOut>(
        "/api/v1/admin/fulfillment/tasks?status_filter=in_progress&limit=200",
      ),
    refetchInterval: 30_000,
  });

  const stuck = useMemo(() => {
    const rows = query.data?.items ?? [];
    const cutoff = Date.now() - STUCK_AFTER_MS;
    return rows.filter((t) => new Date(t.created_at).getTime() < cutoff);
  }, [query.data]);

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "order",
      header: "Order",
      render: (t) => (
        <span className="font-mono text-xs">{t.order_id.slice(0, 8)}…</span>
      ),
      className: "w-28",
    },
    {
      key: "supplier",
      header: "Маршрут",
      render: (t) => <code className="text-xs">{t.supplier}</code>,
      className: "w-32",
    },
    {
      key: "age",
      header: "Ожидание",
      render: (t) => <SlaBadge createdAt={t.created_at} />,
      className: "w-32",
      sortAccessor: (t) => t.created_at,
    },
    {
      key: "attempts",
      header: "Попыток",
      render: (t) => t.attempts_count.toString(),
      className: "w-20 text-center",
    },
    {
      key: "error",
      header: "Последняя ошибка",
      render: (t) =>
        t.last_error ? (
          <span className="text-xs text-[--color-danger]">{t.last_error}</span>
        ) : (
          <span className="text-[--color-muted]">—</span>
        ),
    },
  ];

  return (
    <div>
      <p className="mb-3 text-sm text-[--color-muted]">
        Задачи в работе дольше 30 минут. Чем дольше ждёт — тем хуже SLA.
      </p>
      {query.isError && (
        <p className="mb-3 text-sm text-[--color-danger]">
          Не удалось загрузить список.
        </p>
      )}
      <DataTable
        rows={stuck}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Нет задач, пересидевших порог 30 мин."
        onRowClick={(t) => { void navigate(`/orders/${t.order_id}`); }}
      />
    </div>
  );
}

function SlaBadge({ createdAt }: { createdAt: string }) {
  const ageMs = Date.now() - new Date(createdAt).getTime();
  const ageMin = Math.floor(ageMs / 60_000);
  const tone =
    ageMin >= 120 ? "danger" : ageMin >= 60 ? "warn" : "info";
  return (
    <span
      className={[
        "rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "danger"
          ? "bg-[--color-danger]/15 text-[--color-danger]"
          : tone === "warn"
            ? "bg-amber-100 text-amber-700"
            : "bg-zinc-100 text-zinc-700",
      ].join(" ")}
    >
      {formatAge(ageMs)}
    </span>
  );
}

function formatAge(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes.toString()} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours.toString()} ч`;
  const days = Math.floor(hours / 24);
  return `${days.toString()} дн`;
}
