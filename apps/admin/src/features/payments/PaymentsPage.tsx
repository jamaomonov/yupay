import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useState } from "react";

import {
  type PaymentAdminListOut,
  type PaymentAdminOut,
  type PaymentStatus,
  STATUS_LABEL,
  STATUS_TONE,
} from "./types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { useToast } from "@/components/Toast";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

const PAGE_SIZE = 50;

const STATUSES: { value: PaymentStatus | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending", label: "pending" },
  { value: "requires_action", label: "requires_action" },
  { value: "succeeded", label: "succeeded" },
  { value: "failed", label: "failed" },
  { value: "cancelled", label: "cancelled" },
];

const PROVIDERS = ["", "mock", "click", "payme", "uzum", "yookassa", "tinkoff", "crypto"];

interface SimulateBody {
  outcome: "succeeded" | "failed" | "cancelled";
}

export function PaymentsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [orderId, setOrderId] = useState("");
  const [provider, setProvider] = useState("");
  // Status comes from the URL so Dashboard alert cards can deep-link straight to e.g.
  // ``/payments?status=pending`` (ADR-0017).
  const [status, setStatus] = useSearchParamsState<PaymentStatus | "">("status", "");
  const [offset, setOffset] = useState(0);

  const listQuery = useQuery<PaymentAdminListOut>({
    queryKey: [
      ...qk.payments({
        orderId: orderId || null,
        provider: provider || null,
        status: status || null,
      }),
      "page",
      offset,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (orderId) params.set("order_id", orderId);
      if (provider) params.set("provider", provider);
      if (status) params.set("status_filter", status);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      return apiGet<PaymentAdminListOut>(`/api/v1/admin/payments?${params.toString()}`);
    },
  });

  const simulateMutation = useMutation<
    PaymentAdminOut,
    ApiError,
    { id: string; body: SimulateBody }
  >({
    mutationFn: ({ id, body }) =>
      apiPost<PaymentAdminOut>(`/api/v1/admin/payments/${id}/simulate-webhook`, body),
    onSuccess: (data) => {
      toast.success(`Webhook доставлен → статус: ${data.status}.`);
      void qc.invalidateQueries({ queryKey: ["admin", "payments"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const refundMutation = useMutation<PaymentAdminOut, ApiError, { id: string; reason: string }>({
    mutationFn: ({ id, reason }) =>
      apiPost<PaymentAdminOut>(
        `/api/v1/admin/payments/${id}/refund`,
        { reason },
        { "Idempotency-Key": crypto.randomUUID() },
      ),
    onSuccess: (data) => {
      toast.success(`Возврат оформлен → статус: ${data.status}.`);
      void qc.invalidateQueries({ queryKey: ["admin", "payments"] });
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const columns: Column<PaymentAdminOut>[] = [
    {
      key: "id",
      header: "ID / Order",
      render: (p) => (
        <div className="flex flex-col font-mono text-xs">
          <span>{p.id.slice(0, 8)}…</span>
          <span className="text-[var(--text-secondary)]">order {p.order_id.slice(0, 8)}…</span>
        </div>
      ),
    },
    {
      key: "provider",
      header: "Провайдер",
      render: (p) => <code className="text-xs">{p.provider}</code>,
      className: "w-28",
      sortAccessor: (p) => p.provider,
    },
    {
      key: "status",
      header: "Статус",
      render: (p) => <StatusBadge status={p.status} />,
      className: "w-36",
      sortAccessor: (p) => p.status,
    },
    {
      key: "amount",
      header: "Сумма",
      render: (p) => <span className="font-medium">{formatMoney(p.amount, p.currency)}</span>,
      className: "w-32 text-right",
      sortAccessor: (p) => Number.parseFloat(p.amount) || 0,
    },
    {
      key: "created",
      header: "Создан",
      render: (p) =>
        new Date(p.created_at).toLocaleString("ru", {
          year: "2-digit",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      className: "w-36",
      sortAccessor: (p) => new Date(p.created_at),
    },
    {
      key: "actions",
      header: "",
      render: (p) => (
        <div
          className="flex justify-end gap-1"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          {p.provider === "mock" && (p.status === "pending" || p.status === "requires_action") && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  simulateMutation.mutate({
                    id: p.id,
                    body: { outcome: "succeeded" },
                  });
                }}
              >
                Webhook OK
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  simulateMutation.mutate({
                    id: p.id,
                    body: { outcome: "failed" },
                  });
                }}
              >
                Failed
              </Button>
            </>
          )}
          {(p.status === "succeeded" || p.status === "partially_refunded") && (
            <Button
              variant="danger"
              size="sm"
              disabled={refundMutation.isPending}
              onClick={() => {
                const reason = window.prompt(
                  `Возврат ${formatMoney(p.amount, p.currency)}.\nПричина (видна в audit log):`,
                  "",
                );
                if (reason === null) return;
                refundMutation.mutate({ id: p.id, reason: reason.trim() });
              }}
            >
              Возврат
            </Button>
          )}
        </div>
      ),
      className: "w-52 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Платежи"
        description="Список intent-ов. Для mock-провайдера — кнопки симуляции webhook'а."
        actions={<SaveSegmentButton />}
      />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="text-xs uppercase text-[var(--text-secondary)]">Order ID</label>
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
          <label className="text-xs uppercase text-[var(--text-secondary)]">Провайдер</label>
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setOffset(0);
            }}
            className="mt-1 h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p || "Все"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase text-[var(--text-secondary)]">Статус</label>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as PaymentStatus | "");
              setOffset(0);
            }}
            className="mt-1 h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
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
        rows={listQuery.data?.items ?? []}
        columns={columns}
        rowKey={(p) => p.id}
        loading={listQuery.isPending}
        empty="Платежей нет."
      />

      <Pagination
        total={listQuery.data?.total ?? 0}
        limit={PAGE_SIZE}
        offset={offset}
        onPageChange={setOffset}
      />
    </div>
  );
}

function StatusBadge({ status }: { status: PaymentStatus }) {
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
