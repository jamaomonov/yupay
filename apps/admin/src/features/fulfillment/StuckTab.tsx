/**
 * Stuck tab — tasks in_progress longer than the SLA threshold.
 *
 * The "stuck" status is computed client-side from ``created_at`` because the
 * existing /admin/fulfillment/tasks endpoint doesn't filter by age. A task
 * that legitimately stays in_progress (manual queue) shows up here once it
 * crosses 30 min, which is intentional — the operator should pick it up.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { selectStuckRows, stuckTasksQuery } from "./inboxQueries";

import type { TaskAdminOut, TaskListOut } from "./types";

import { Badge } from "@/components/Badge";
import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";

export function StuckTab() {
  const navigate = useNavigate();
  // Shared with the Inbox badge — see ``inboxQueries``.
  const query = useQuery<TaskListOut>(stuckTasksQuery);

  const stuck = useMemo(() => selectStuckRows(query.data), [query.data]);

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "order",
      header: "Order",
      render: (t) => <CopyId value={t.order_id} to={`/orders/${t.order_id}`} className="text-xs" />,
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
          <span className="text-xs text-[var(--danger)]">{t.last_error}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        ),
    },
  ];

  return (
    <div>
      <p className="mb-3 text-sm text-[var(--text-secondary)]">
        Задачи в работе дольше 30 минут. Чем дольше ждёт — тем хуже SLA.
      </p>
      {query.isError && (
        <p className="mb-3 text-sm text-[var(--danger)]">Не удалось загрузить список.</p>
      )}
      <DataTable
        rows={stuck}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Нет задач, пересидевших порог 30 мин."
        onRowClick={(t) => {
          void navigate(`/orders/${t.order_id}`);
        }}
      />
    </div>
  );
}

function SlaBadge({ createdAt }: { createdAt: string }) {
  const ageMs = Date.now() - new Date(createdAt).getTime();
  const ageMin = Math.floor(ageMs / 60_000);
  const tone = ageMin >= 120 ? "danger" : ageMin >= 60 ? "warn" : "info";
  const cls =
    tone === "danger"
      ? "bg-[var(--danger-soft)] text-[var(--danger-fg)]"
      : tone === "warn"
        ? "bg-[var(--warning-soft)] text-[var(--warning-fg)]"
        : "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
  return (
    <Badge tone={cls} dot={tone !== "info"}>
      {formatAge(ageMs)}
    </Badge>
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
