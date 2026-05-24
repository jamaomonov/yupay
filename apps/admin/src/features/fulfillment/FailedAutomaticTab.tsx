/**
 * Failed-automatic tab — supplier returned failure, the task is sitting in
 * ``failed`` waiting for an admin decision.
 *
 * Operator workflow: tick the rows worth retrying, click "Retry N", see the
 * bulk response — what got re-queued and what was skipped (succeeded /
 * cancelled / unknown). Manual tasks (supplier=manual) don't appear here:
 * they're closed via the modal in the "Ручная выдача" tab, not by retry.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { TaskAdminOut, TaskListOut } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface BulkRetryResponse {
  retried: TaskAdminOut[];
  skipped: { id: string; reason: string }[];
}

export function FailedAutomaticTab() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [feedback, setFeedback] = useState<string | null>(null);

  const query = useQuery<TaskListOut>({
    queryKey: [...qk.fulfillmentTasks({ status: "failed" }), "no-manual"],
    queryFn: () =>
      apiGet<TaskListOut>("/api/v1/admin/fulfillment/tasks?status_filter=failed&limit=200"),
    refetchInterval: 30_000,
  });

  const rows = useMemo(
    // Manual tasks land in the dedicated tab; here we focus on automatic
    // failures where retry makes sense.
    () => (query.data?.items ?? []).filter((t) => t.supplier !== "manual"),
    [query.data],
  );

  const bulkRetry = useMutation<BulkRetryResponse, ApiError, string[]>({
    mutationFn: (ids) =>
      apiPost<BulkRetryResponse>("/api/v1/admin/fulfillment/tasks/bulk-retry", { task_ids: ids }),
    onSuccess: (data) => {
      const retriedN = data.retried.length;
      const skippedN = data.skipped.length;
      const parts = [`Перезапущено: ${retriedN.toString()}`];
      if (skippedN > 0) parts.push(`пропущено: ${skippedN.toString()}`);
      setFeedback(parts.join(" · "));
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      setFeedback(`Ошибка: ${err.message}`);
    },
  });

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleAll = () => {
    setSelected((prev) => (prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id))));
  };

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "select",
      header: "",
      render: (t) => (
        <input
          type="checkbox"
          checked={selected.has(t.id)}
          onClick={(e) => {
            e.stopPropagation();
          }}
          onChange={() => {
            toggle(t.id);
          }}
          aria-label={`Выбрать ${t.id.slice(0, 8)}`}
        />
      ),
      className: "w-10",
    },
    {
      key: "order",
      header: "Order",
      render: (t) => <span className="font-mono text-xs">{t.order_id.slice(0, 8)}…</span>,
      className: "w-28",
    },
    {
      key: "supplier",
      header: "Маршрут",
      render: (t) => <code className="text-xs">{t.supplier}</code>,
      className: "w-32",
    },
    {
      key: "attempts",
      header: "Попыток",
      render: (t) => t.attempts_count.toString(),
      className: "w-20 text-center",
    },
    {
      key: "error",
      header: "Ошибка",
      render: (t) =>
        t.last_error ? (
          <span className="text-xs text-[var(--danger)]">{t.last_error}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        ),
    },
    {
      key: "age",
      header: "Failed",
      render: (t) => (t.failed_at ? new Date(t.failed_at).toLocaleString("ru") : "—"),
      className: "w-40",
      sortAccessor: (t) => t.failed_at,
    },
  ];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[var(--text-secondary)]">
          Автоматические задачи, которые упали. Отметь и нажми «Перезапустить» — бэк сам пропустит
          те, что уже не подлежат retry.
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleAll}
            className="text-xs text-[var(--text-secondary)] underline-offset-2 hover:underline disabled:opacity-50"
            disabled={rows.length === 0}
          >
            {selected.size === rows.length && rows.length > 0 ? "Снять выбор" : "Выбрать все"}
          </button>
          <Button
            type="button"
            onClick={() => {
              bulkRetry.mutate([...selected]);
            }}
            disabled={selected.size === 0 || bulkRetry.isPending}
          >
            {bulkRetry.isPending ? "Перезапуск…" : `Перезапустить ${selected.size.toString()}`}
          </Button>
        </div>
      </div>

      {feedback && <p className="mb-3 text-sm text-[var(--text-primary)]">{feedback}</p>}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Нет failed-задач — всё хорошо."
        onRowClick={(t) => {
          void navigate(`/orders/${t.order_id}`);
        }}
      />
    </div>
  );
}
