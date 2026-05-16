import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type { TaskAdminOut, TaskListOut, TaskStatus } from "./types";

const STATUSES: { value: TaskStatus | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending", label: "pending" },
  { value: "in_progress", label: "in_progress" },
  { value: "succeeded", label: "succeeded" },
  { value: "failed", label: "failed" },
  { value: "cancelled", label: "cancelled" },
];

export function FulfillmentPage() {
  const qc = useQueryClient();
  const [orderId, setOrderId] = useState("");
  const [supplier, setSupplier] = useState("");
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const tasksQuery = useQuery<TaskListOut>({
    queryKey: qk.fulfillmentTasks({
      orderId: orderId || null,
      supplier: supplier || null,
      status: status || null,
    }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (orderId) params.set("order_id", orderId);
      if (supplier) params.set("supplier", supplier);
      if (status) params.set("status_filter", status);
      params.set("limit", "100");
      return apiGet<TaskListOut>(
        `/api/v1/admin/fulfillment/tasks?${params.toString()}`,
      );
    },
  });

  const retryMutation = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (id) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/${id}/retry`, {}),
    onSuccess: () => {
      setFeedback("Retry запущен.");
      setError(null);
      void qc.invalidateQueries({
        queryKey: ["admin", "fulfillment"],
      });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const cancelMutation = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (id) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/${id}/cancel`, {}),
    onSuccess: () => {
      setFeedback("Задача отменена.");
      setError(null);
      void qc.invalidateQueries({
        queryKey: ["admin", "fulfillment"],
      });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "order",
      header: "Order / item",
      render: (t) => (
        <div className="flex flex-col font-mono text-xs">
          <span>{t.order_id.slice(0, 8)}…</span>
          <span className="text-[--color-muted]">
            item {t.order_item_id.slice(0, 8)}…
          </span>
        </div>
      ),
    },
    {
      key: "supplier",
      header: "Маршрут",
      render: (t) => (
        <code className="text-xs">{t.supplier}</code>
      ),
      className: "w-32",
    },
    {
      key: "status",
      header: "Статус",
      render: (t) => <StatusBadge status={t.status} />,
      className: "w-32",
    },
    {
      key: "attempts",
      header: "Попыток",
      render: (t) => t.attempts_count,
      className: "w-20 text-center",
    },
    {
      key: "error",
      header: "Ошибка",
      render: (t) =>
        t.last_error ? (
          <span className="text-xs text-[--color-danger]">{t.last_error}</span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: "",
      render: (t) => (
        <div
          className="flex justify-end gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          {(t.status === "failed" || t.status === "pending") && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => retryMutation.mutate(t.id)}
            >
              Retry
            </Button>
          )}
          {t.status !== "succeeded" && t.status !== "cancelled" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (window.confirm("Отменить задачу?")) {
                  cancelMutation.mutate(t.id);
                }
              }}
            >
              Cancel
            </Button>
          )}
        </div>
      ),
      className: "w-44 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Fulfilment"
        description="Задачи саги: статусы, попытки, retry / cancel."
      />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="text-xs uppercase text-[--color-muted]">
            Order ID
          </label>
          <Input
            value={orderId}
            onChange={(e) => setOrderId(e.target.value)}
            placeholder="UUID"
            className="mt-1 font-mono text-xs"
          />
        </div>
        <div>
          <label className="text-xs uppercase text-[--color-muted]">
            Маршрут
          </label>
          <Input
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            placeholder="inventory / mock / steam / ..."
            className="mt-1 text-sm"
          />
        </div>
        <div>
          <label className="text-xs uppercase text-[--color-muted]">
            Статус
          </label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as TaskStatus | "")}
            className="mt-1 h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      {(feedback || error) && (
        <div className="mb-3 text-sm">
          {feedback && <span className="text-[--color-success]">{feedback}</span>}
          {error && <span className="text-[--color-danger]">{error}</span>}
        </div>
      )}

      <DataTable
        rows={tasksQuery.data?.items ?? []}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Задач не нашлось."
        onRowClick={(t) => setExpanded(expanded === t.id ? null : t.id)}
      />

      {expanded && (
        <div className="mt-4">
          {(tasksQuery.data?.items ?? [])
            .filter((t) => t.id === expanded)
            .map((t) => (
              <TaskDetails key={t.id} task={t} />
            ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const map: Record<TaskStatus, string> = {
    pending: "bg-zinc-100 text-zinc-700",
    in_progress: "bg-amber-100 text-amber-700",
    succeeded: "bg-emerald-100 text-emerald-700",
    failed: "bg-rose-100 text-rose-700",
    cancelled: "bg-zinc-100 text-zinc-600",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${map[status]}`}>
      {status}
    </span>
  );
}

function TaskDetails({ task }: { task: TaskAdminOut }) {
  return (
    <article className="rounded-lg border bg-[--color-bg] p-4 text-sm">
      <h3 className="mb-2 text-sm font-semibold">
        Аттемпты — {task.attempts.length}
      </h3>
      {task.attempts.length === 0 ? (
        <p className="text-[--color-muted]">Попыток ещё не было.</p>
      ) : (
        <ol className="space-y-2">
          {task.attempts.map((a, i) => (
            <li
              key={`${a.kind}-${a.created_at}-${i}`}
              className="rounded border border-[--color-border]/50 p-2 text-xs"
            >
              <div className="flex justify-between">
                <span>
                  <code>{a.kind}</code> ·{" "}
                  <span
                    className={
                      a.status === "ok"
                        ? "text-[--color-success]"
                        : "text-[--color-danger]"
                    }
                  >
                    {a.status}
                  </span>
                </span>
                <span className="text-[--color-muted]">
                  {new Date(a.created_at).toLocaleString("ru")}
                </span>
              </div>
              {a.error && (
                <pre className="mt-1 whitespace-pre-wrap text-[--color-danger]">
                  {a.error}
                </pre>
              )}
              {Object.keys(a.payload).length > 0 && (
                <pre className="mt-1 whitespace-pre-wrap text-[--color-muted]">
                  {JSON.stringify(a.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
