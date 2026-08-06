/**
 * Manual-fulfilment queue.
 *
 * Lists every task with ``supplier=manual`` + ``status=in_progress`` — the
 * exact backend filter is the existing ``/admin/fulfillment/tasks``
 * endpoint with frozen query params. We resolve each task's order detail
 * client-side (single ``/admin/orders/{id}`` per row) so admins see brand,
 * customer + fulfillment_data preview without expanding the row. Volumes
 * here are low; a server-side embed only earns its keep once the manual
 * queue actually grows.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ManualTaskModal } from "./ManualTaskModal";

import type {
  TaskAdminOut,
  TaskListOut as FulfillmentTaskListOut,
} from "@/features/fulfillment/types";
import type { OrderAdminOut } from "@/features/orders/types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { manualQueueQuery } from "@/features/fulfillment/inboxQueries";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface QueueRow {
  task: TaskAdminOut;
  order: OrderAdminOut | null;
  orderLoading: boolean;
}

export function ManualQueuePage() {
  // Shared with the Inbox badge — see ``fulfillment/inboxQueries``.
  const tasksQuery = useQuery<FulfillmentTaskListOut>(manualQueueQuery);

  const tasks = tasksQuery.data?.items ?? [];

  // Fan-out: pull the order detail per row. ``useQueries`` shares the
  // ``["admin","orders", id]`` cache key with OrderDetailPage so opening
  // the corresponding order page later is instant.
  const orderQueries = useQueries({
    queries: tasks.map((task) => ({
      queryKey: qk.order(task.order_id),
      queryFn: () => apiGet<OrderAdminOut>(`/api/v1/admin/orders/${task.order_id}`),
      staleTime: 30_000,
    })),
  });

  const rows: QueueRow[] = tasks.map((task, idx) => ({
    task,
    order: orderQueries[idx]?.data ?? null,
    orderLoading: orderQueries[idx]?.isPending ?? false,
  }));

  const [openTask, setOpenTask] = useState<TaskAdminOut | null>(null);

  const columns: Column<QueueRow>[] = [
    {
      key: "order",
      header: "Заказ",
      render: (r) => (
        <div className="flex flex-col">
          <CopyId value={r.task.order_id} className="text-xs text-[var(--text-secondary)]" />
          <span className="text-xs text-[var(--text-secondary)]">
            {r.order
              ? new Date(r.order.created_at).toLocaleString("ru", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : r.orderLoading
                ? "…"
                : "—"}
          </span>
        </div>
      ),
      sortAccessor: (r) => r.order?.created_at ?? null,
    },
    {
      key: "product",
      header: "Товар",
      render: (r) => {
        const item = orderItem(r);
        const display = item?.display;
        if (!display) return <span className="text-[var(--text-secondary)]">—</span>;
        const denom = display.denomination ?? display.sku_code;
        return (
          <div className="flex flex-col">
            <span className="font-medium">{display.brand_name || display.product_name}</span>
            <span className="text-xs text-[var(--text-secondary)]">{denom}</span>
          </div>
        );
      },
    },
    {
      key: "customer",
      header: "Клиент",
      render: (r) => (
        <span className="text-sm">
          {r.order
            ? (r.order.guest_email ??
              (r.order.user_id ? `user:${r.order.user_id.slice(0, 8)}…` : "—"))
            : "…"}
        </span>
      ),
    },
    {
      key: "data",
      header: "Данные",
      render: (r) => {
        const item = orderItem(r);
        if (!item) return <span className="text-[var(--text-secondary)]">…</span>;
        const entries = Object.entries(item.fulfillment_data).filter(
          ([, v]) => v !== null && v !== "",
        );
        if (entries.length === 0) {
          return <span className="text-[var(--text-secondary)]">—</span>;
        }
        return (
          <ul className="space-y-0.5 text-xs">
            {entries.slice(0, 2).map(([k, v]) => (
              <li key={k} className="font-mono">
                <span className="text-[var(--text-secondary)]">{k}:</span> {String(v).slice(0, 24)}
              </li>
            ))}
            {entries.length > 2 && (
              <li className="text-[var(--text-secondary)]">+{entries.length - 2}</li>
            )}
          </ul>
        );
      },
    },
    {
      key: "amount",
      header: "Сумма",
      className: "text-right",
      render: (r) => (
        <span className="font-mono text-sm">
          {r.order
            ? `${Number.parseFloat(r.order.total_charged).toLocaleString("ru", {
                maximumFractionDigits: 2,
              })} ${r.order.currency}`
            : "—"}
        </span>
      ),
      sortAccessor: (r) => (r.order ? Number.parseFloat(r.order.total_charged) : 0),
    },
    {
      key: "age",
      header: "Возраст",
      render: (r) => (
        <span className="text-xs text-[var(--text-secondary)]">{formatAge(r.task.created_at)}</span>
      ),
      sortAccessor: (r) => r.task.created_at,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Ручная выдача"
        description="Заказы по SKU без авто-поставщика. Открой задачу, чтобы завершить или отклонить."
      />

      {tasksQuery.isError && (
        <p className="mb-3 text-sm text-[var(--danger)]">
          Не удалось загрузить очередь:{" "}
          {(tasksQuery.error as Error | undefined)?.message ?? "ошибка сети"}
        </p>
      )}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.task.id}
        empty="Очередь пуста — все ручные задачи обработаны."
        onRowClick={(r) => {
          setOpenTask(r.task);
        }}
      />

      {openTask && (
        <ManualTaskModal
          task={openTask}
          onClose={() => {
            setOpenTask(null);
          }}
        />
      )}
    </div>
  );
}

function orderItem(row: QueueRow) {
  return row.order?.items.find((i) => i.id === row.task.order_item_id) ?? null;
}

function formatAge(createdIso: string): string {
  const diffMs = Date.now() - new Date(createdIso).getTime();
  if (!Number.isFinite(diffMs) || diffMs < 0) return "—";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds} с`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч`;
  const days = Math.floor(hours / 24);
  return `${days} дн`;
}
