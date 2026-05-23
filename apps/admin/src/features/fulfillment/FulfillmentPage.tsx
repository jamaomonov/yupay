import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { Pagination } from "@/components/Pagination";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useSearchParamsState } from "@/lib/useSearchParamsState";
import { useToast } from "@/components/Toast";

const PAGE_SIZE = 50;

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
  const toast = useToast();
  const [orderId, setOrderId] = useState("");
  const [supplier, setSupplier] = useState("");
  // Status is URL-bound so Dashboard alerts can deep-link to e.g.
  // ``/fulfillment?status=pending`` (ADR-0017).
  const [status, setStatus] = useSearchParamsState<TaskStatus | "">("status", "");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const tasksQuery = useQuery<TaskListOut>({
    queryKey: [
      ...qk.fulfillmentTasks({
        orderId: orderId || null,
        supplier: supplier || null,
        status: status || null,
      }),
      "page",
      offset,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (orderId) params.set("order_id", orderId);
      if (supplier) params.set("supplier", supplier);
      if (status) params.set("status_filter", status);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<TaskListOut>(
        `/api/v1/admin/fulfillment/tasks?${params.toString()}`,
      );
    },
  });

  const retryMutation = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (id) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/${id}/retry`, {}),
    onSuccess: () => {
      toast.success("Retry запущен.");
      void qc.invalidateQueries({
        queryKey: ["admin", "fulfillment"],
      });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const cancelMutation = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (id) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/${id}/cancel`, {}),
    onSuccess: () => {
      toast.success("Задача отменена.");
      void qc.invalidateQueries({
        queryKey: ["admin", "fulfillment"],
      });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "order",
      header: "Order / item",
      render: (t) => (
        <div className="flex flex-col font-mono text-xs">
          <span>{t.order_id.slice(0, 8)}…</span>
          <span className="text-[--text-secondary]">
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
      sortAccessor: (t) => t.supplier,
    },
    {
      key: "status",
      header: "Статус",
      render: (t) => <StatusBadge status={t.status} />,
      className: "w-32",
      sortAccessor: (t) => t.status,
    },
    {
      key: "attempts",
      header: "Попыток",
      render: (t) => t.attempts_count,
      className: "w-20 text-center",
      sortAccessor: (t) => t.attempts_count,
    },
    {
      key: "error",
      header: "Ошибка",
      render: (t) =>
        t.last_error ? (
          <span className="text-xs text-[--danger]">{t.last_error}</span>
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
          <label className="text-xs uppercase text-[--text-secondary]">
            Order ID
          </label>
          <Input
            value={orderId}
            onChange={(e) => {
              setOrderId(e.target.value);
              setOffset(0);
            }}
            placeholder="UUID"
            className="mt-1 font-mono text-xs"
          />
        </div>
        <div>
          <label className="text-xs uppercase text-[--text-secondary]">
            Маршрут
          </label>
          <Input
            value={supplier}
            onChange={(e) => {
              setSupplier(e.target.value);
              setOffset(0);
            }}
            placeholder="inventory / mock / steam / ..."
            className="mt-1 text-sm"
          />
        </div>
        <div>
          <label className="text-xs uppercase text-[--text-secondary]">
            Статус
          </label>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as TaskStatus | "");
              setOffset(0);
            }}
            className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      <DataTable
        rows={tasksQuery.data?.items ?? []}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Задач не нашлось."
        onRowClick={(t) => setExpanded(expanded === t.id ? null : t.id)}
      />

      <Pagination
        total={tasksQuery.data?.total ?? 0}
        limit={PAGE_SIZE}
        offset={offset}
        onPageChange={setOffset}
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
    pending: "bg-[--bg-muted] text-[--text-secondary]",
    in_progress: "bg-[--warning-soft] text-[--warning-fg]",
    succeeded: "bg-[--success-soft] text-[--success-fg]",
    failed: "bg-[--danger-soft] text-[--danger-fg]",
    cancelled: "bg-[--bg-muted] text-[--text-secondary]",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${map[status]}`}>
      {status}
    </span>
  );
}

function TaskDetails({ task }: { task: TaskAdminOut }) {
  const proofUrl = typeof task.extra_metadata.proof_url === "string"
    ? task.extra_metadata.proof_url
    : null;
  const queuedAt = typeof task.extra_metadata.queued_at === "string"
    ? task.extra_metadata.queued_at
    : null;
  const otherMeta = Object.fromEntries(
    Object.entries(task.extra_metadata).filter(
      ([k]) => k !== "proof_url" && k !== "queued_at",
    ),
  );

  return (
    <article className="space-y-4 rounded-lg border bg-[--bg-surface] p-4 text-sm">
      {/* Task header — basic fields + lifecycle timestamps. */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <DetailField label="ID" value={task.id} mono />
        <DetailField label="Маршрут" value={task.supplier} mono />
        <DetailField label="Статус" value={task.status} />
        <DetailField
          label="Создана"
          value={new Date(task.created_at).toLocaleString("ru")}
        />
        {task.succeeded_at && (
          <DetailField
            label="Завершена"
            value={new Date(task.succeeded_at).toLocaleString("ru")}
          />
        )}
        {task.failed_at && (
          <DetailField
            label="Провалена"
            value={new Date(task.failed_at).toLocaleString("ru")}
          />
        )}
        {task.cancelled_at && (
          <DetailField
            label="Отменена"
            value={new Date(task.cancelled_at).toLocaleString("ru")}
          />
        )}
        {task.external_order_id && (
          <DetailField label="External order" value={task.external_order_id} mono />
        )}
        {queuedAt && (
          <DetailField
            label="Поставлена в очередь"
            value={new Date(queuedAt).toLocaleString("ru")}
          />
        )}
      </section>

      {/* Manual-fulfilment audit. Only show the block when at least one
          of the manual fields is set — for supplier-driven tasks the
          whole block stays hidden. */}
      {(task.completed_by || task.admin_note || proofUrl) && (
        <section className="space-y-2 rounded-md border border-[--border-default]/60 bg-[--bg-muted]/40 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[--text-secondary]">
            Ручная обработка
          </h4>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {task.completed_by && (
              <DetailField label="Обработал admin" value={task.completed_by} mono />
            )}
            {task.admin_note && (
              <DetailField label="Заметка" value={task.admin_note} />
            )}
          </div>
          {proofUrl && (
            <a
              href={proofUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-[--accent] hover:underline"
            >
              <ExternalLink className="size-3.5" />
              Открыть пруф
            </a>
          )}
        </section>
      )}

      {/* Any extra_metadata keys we don't explicitly render — dump as JSON
          so they don't get lost when a supplier sets a custom field. */}
      {Object.keys(otherMeta).length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[--text-secondary]">
            Метаданные
          </h4>
          <pre className="whitespace-pre-wrap rounded border border-[--border-default]/50 bg-[--bg-muted]/40 p-2 text-xs">
            {JSON.stringify(otherMeta, null, 2)}
          </pre>
        </section>
      )}

      {/* Attempts log. */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[--text-secondary]">
          Аттемпты — {task.attempts.length}
        </h4>
        {task.attempts.length === 0 ? (
          <p className="text-[--text-secondary]">Попыток ещё не было.</p>
        ) : (
          <ol className="space-y-2">
            {task.attempts.map((a, i) => (
              <li
                key={`${a.kind}-${a.created_at}-${i}`}
                className="rounded border border-[--border-default]/50 p-2 text-xs"
              >
                <div className="flex justify-between">
                  <span>
                    <code>{a.kind}</code> ·{" "}
                    <span
                      className={
                        a.status === "ok"
                          ? "text-[--success]"
                          : "text-[--danger]"
                      }
                    >
                      {a.status}
                    </span>
                  </span>
                  <span className="text-[--text-secondary]">
                    {new Date(a.created_at).toLocaleString("ru")}
                  </span>
                </div>
                {a.error && (
                  <pre className="mt-1 whitespace-pre-wrap text-[--danger]">
                    {a.error}
                  </pre>
                )}
                {Object.keys(a.payload).length > 0 && (
                  <pre className="mt-1 whitespace-pre-wrap text-[--text-secondary]">
                    {JSON.stringify(a.payload, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  );
}

function DetailField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-[--text-secondary]">{label}</p>
      <p
        className={[
          "mt-0.5 break-words text-sm",
          mono ? "font-mono text-xs" : "",
        ].join(" ")}
      >
        {value}
      </p>
    </div>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
