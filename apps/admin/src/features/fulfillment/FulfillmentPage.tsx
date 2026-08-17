import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { useEffect, useId, useState } from "react";

import { TaskDetailPanel } from "./TaskDetailPanel";

import type { TaskAdminOut, TaskListOut, TaskStatus } from "./types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusChip } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

const PAGE_SIZE = 50;

const STATUSES: { value: TaskStatus | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending", label: "pending" },
  { value: "in_progress", label: "in_progress" },
  { value: "succeeded", label: "succeeded" },
  { value: "failed", label: "failed" },
  { value: "cancelled", label: "cancelled" },
];

// Route is the persisted ``fulfillment_tasks.supplier`` value:
// ``inventory`` for the warehouse, the bare supplier slug otherwise.
// Listing the known routes as a picker beats a free-text field where a
// typo silently returns zero rows.
// Built from the shared route table. The hand-written list this replaced had
// drifted badly: it offered steam/riot/pubg/spotify/apple — stubs that have
// never produced a task — while omitting waxpeer and gengine, which produce
// all of them.
const ROUTES: { value: string; label: string }[] = [
  { value: "", label: "Все маршруты" },
  ...FULFILMENT_ROUTES.map((r) => ({ value: r.slug, label: r.label })),
];

export function FulfillmentPage() {
  // Ties each filter's visible <label> to its control; a plain sibling
  // label names nothing for a screen reader.
  const fieldId = useId();
  const qc = useQueryClient();
  const toast = useToast();
  // `orderId` is what the query uses; `orderDraft` is what the field shows.
  // A UUID typed straight into the query fired one request per character.
  const [orderId, setOrderId] = useState("");
  const [orderDraft, setOrderDraft] = useState("");
  const [supplier, setSupplier] = useState("");
  // Status is URL-bound so Dashboard alerts can deep-link to e.g.
  // ``/fulfillment?status=pending`` (ADR-0017).
  const [status, setStatus] = useSearchParamsState<TaskStatus | "">("status", "");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (orderDraft === orderId) return;
    const timer = setTimeout(() => {
      setOrderId(orderDraft.trim());
      setOffset(0);
    }, 350);
    return () => {
      clearTimeout(timer);
    };
  }, [orderDraft, orderId]);

  // A selection only means something within the page it was made on. Left
  // alone, changing a filter or paging away kept `expanded` pointing at a row
  // that is no longer listed, and the panel just vanished with no explanation.
  useEffect(() => {
    setExpanded(null);
  }, [orderId, supplier, status, offset]);

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
      return apiGet<TaskListOut>(`/api/v1/admin/fulfillment/tasks?${params.toString()}`);
    },
  });

  const retryMutation = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (id) => apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${id}/retry`, {}),
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
    mutationFn: (id) => apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${id}/cancel`, {}),
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

  // Resolved from the page in hand rather than refetched: the row is already
  // loaded, and a selection can only point at something on this page.
  const selectedTask = (tasksQuery.data?.items ?? []).find((t) => t.id === expanded) ?? null;

  const columns: Column<TaskAdminOut>[] = [
    {
      key: "order",
      header: "Order / item",
      render: (t) => (
        <div className="flex flex-col font-mono text-xs">
          <CopyId value={t.order_id} to={`/orders/${t.order_id}`} />
          <CopyId value={t.order_item_id} label="item" className="text-[var(--text-secondary)]" />
        </div>
      ),
    },
    {
      key: "supplier",
      header: "Маршрут",
      render: (t) => <code className="text-xs">{t.supplier}</code>,
      className: "w-32",
      sortAccessor: (t) => t.supplier,
    },
    {
      key: "status",
      header: "Статус",
      render: (t) => <StatusChip domain="taskStatus" value={t.status} />,
      className: "w-32",
      sortAccessor: (t) => t.status,
    },
    {
      key: "attempts",
      header: "Обращений",
      // Not "attempts to deliver": every status poll counts here too, and a
      // task left open by a slow supplier polls once a minute — one live task
      // reads 1641 while having been fulfilled exactly once. Naming the column
      // after what it counts stops that number reading as an alarm.
      render: (t) => (
        <span title="Обращений к поставщику, включая проверки статуса">{t.attempts_count}</span>
      ),
      className: "w-24 text-center",
      sortAccessor: (t) => t.attempts_count,
    },
    {
      key: "error",
      header: "Ошибка",
      render: (t) =>
        t.last_error ? <span className="text-xs text-[var(--danger)]">{t.last_error}</span> : "—",
    },
    {
      key: "actions",
      header: "",
      render: (t) => (
        <div
          className="flex justify-end gap-1"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          {(t.status === "failed" || t.status === "pending") && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                retryMutation.mutate(t.id);
              }}
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
      <PageHeader title="Fulfilment" description="Задачи саги: статусы, попытки, retry / cancel." />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="text-xs uppercase text-[var(--text-secondary)]">Order ID</label>
          <Input
            value={orderDraft}
            onChange={(e) => {
              setOrderDraft(e.target.value);
            }}
            placeholder="UUID"
            className="mt-1 font-mono text-xs"
          />
        </div>
        <div>
          <label
            htmlFor={`${fieldId}-f0`}
            className="text-xs uppercase text-[var(--text-secondary)]"
          >
            Маршрут
          </label>
          <Select
            id={`${fieldId}-f0`}
            value={supplier}
            onChange={(e) => {
              setSupplier(e.target.value);
              setOffset(0);
            }}
            containerClassName="mt-1 w-full"
          >
            {ROUTES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <label
            htmlFor={`${fieldId}-f1`}
            className="text-xs uppercase text-[var(--text-secondary)]"
          >
            Статус
          </label>
          <Select
            id={`${fieldId}-f1`}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as TaskStatus | "");
              setOffset(0);
            }}
            containerClassName="mt-1 w-full"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </div>
      </section>

      {/* Table and detail side by side: the panel used to render *below* the
          pagination, so opening a row on a 50-row page threw the operator to
          the bottom of the document and closing it threw them back. Here the
          selection just updates a panel that is already on screen, and on a
          wide viewport it sticks while the list scrolls under it. */}
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0">
          <DataTable
            rows={tasksQuery.data?.items ?? []}
            columns={columns}
            rowKey={(t) => t.id}
            loading={tasksQuery.isPending}
            busy={tasksQuery.isFetching}
            empty="Задач не нашлось."
            ariaLabel="Задачи фулфилмента"
            selectedKey={expanded}
            onRowClick={(t) => {
              setExpanded(expanded === t.id ? null : t.id);
            }}
          />

          <Pagination
            total={tasksQuery.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onPageChange={setOffset}
          />
        </div>

        {selectedTask && (
          <div className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto">
            <TaskDetailPanel
              task={selectedTask}
              onClose={() => {
                setExpanded(null);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
