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
import { AlertTriangle, Wallet } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ForceCompleteModal } from "./ForceCompleteModal";
import { failedTasksQuery, selectFailedRows } from "./inboxQueries";

import type { TaskAdminOut, TaskListOut } from "./types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { type ApiError, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

const LOW_BALANCE_ERROR = "supplier_low_balance";

interface BulkRetryResponse {
  retried: TaskAdminOut[];
  skipped: { id: string; reason: string }[];
}

export function FailedAutomaticTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [forceCompleteFor, setForceCompleteFor] = useState<TaskAdminOut | null>(null);

  // Query + predicate come from ``inboxQueries`` so the Inbox tab badge counts
  // exactly the rows rendered here (manual tasks live in their own tab).
  const query = useQuery<TaskListOut>(failedTasksQuery);

  const rows = useMemo(() => selectFailedRows(query.data), [query.data]);

  const bulkRetry = useMutation<BulkRetryResponse, ApiError, string[]>({
    mutationFn: (ids) =>
      apiPost<BulkRetryResponse>("/api/v1/admin/fulfillment/tasks/bulk-retry", { task_ids: ids }),
    onSuccess: (data) => {
      const retriedN = data.retried.length;
      const skippedN = data.skipped.length;
      const parts = [`Перезапущено: ${retriedN.toString()}`];
      if (skippedN > 0) parts.push(`пропущено: ${skippedN.toString()}`);
      // Toast rather than a bare <p>: bulk-retry spends supplier balance, so the
      // outcome needs the toast region's role="alert", not a line the operator
      // may have already scrolled past.
      toast.success(parts.join(" · "));
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
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
      key: "attempts",
      header: "Попыток",
      render: (t) => t.attempts_count.toString(),
      className: "w-20 text-center",
    },
    {
      key: "error",
      header: "Ошибка",
      render: (t) => {
        if (t.last_error === LOW_BALANCE_ERROR) {
          return (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--bg-muted)] px-2.5 py-0.5 text-xs font-medium text-[var(--danger)]"
              title="Поставщик отверг заказ из-за недостатка средств. Клиент видит «в обработке»."
            >
              <Wallet className="size-3.5" aria-hidden />
              Низкий баланс
            </span>
          );
        }
        return t.last_error ? (
          <span className="text-xs text-[var(--danger)]">{t.last_error}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        );
      },
    },
    {
      key: "age",
      header: "Failed",
      render: (t) => (t.failed_at ? new Date(t.failed_at).toLocaleString("ru") : "—"),
      className: "w-40",
      sortAccessor: (t) => t.failed_at,
    },
    {
      key: "actions",
      header: "",
      render: (t) => {
        if (t.last_error !== LOW_BALANCE_ERROR) return null;
        return (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setForceCompleteFor(t);
            }}
            className="text-xs text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
          >
            Завершить вручную
          </button>
        );
      },
      className: "w-32 text-right",
    },
  ];

  const lowBalanceRows = rows.filter((r) => r.last_error === LOW_BALANCE_ERROR);

  return (
    <div>
      {lowBalanceRows.length > 0 && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-3 rounded-md border border-[var(--danger)] bg-[var(--bg-muted)] p-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-[var(--danger)]" aria-hidden />
          <div className="flex-1">
            <strong>Низкий баланс у поставщика: {lowBalanceRows.length.toString()} задач.</strong>{" "}
            Клиенты видят «в обработке». Пополните счёт у G2B и нажмите «Перезапустить» по каждой
            задаче, либо «Завершить вручную» если выдали код off-platform.
          </div>
        </div>
      )}

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

      {/* A failed request must not render as "all good" on the very screen whose
          job is to surface failures. */}
      {query.isError ? (
        <ErrorState
          description={extractApiMessage(query.error)}
          onRetry={() => void query.refetch()}
          retryPending={query.isFetching}
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(t) => t.id}
          loading={query.isLoading}
          busy={query.isFetching}
          empty="Нет failed-задач — всё хорошо."
          onRowClick={(t) => {
            void navigate(`/orders/${t.order_id}`);
          }}
        />
      )}

      {forceCompleteFor && (
        <ForceCompleteModal
          task={forceCompleteFor}
          onClose={() => {
            setForceCompleteFor(null);
          }}
          onCompleted={() => {
            setForceCompleteFor(null);
            void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
          }}
        />
      )}
    </div>
  );
}
