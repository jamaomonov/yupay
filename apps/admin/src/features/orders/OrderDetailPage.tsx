import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Ban,
  Check,
  CircleDot,
  Clock,
  Coins,
  CreditCard,
  Package,
  Truck,
} from "lucide-react";

import { Button } from "@yupay/ui";
import { Spinner } from "@/components/States";

import { PageHeader } from "@/components/PageHeader";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type {
  PaymentAdminListOut,
  PaymentAdminOut,
} from "@/features/payments/types";
import type { TaskAdminOut, TaskListOut } from "@/features/fulfillment/types";

import {
  type OrderAdminOut,
  type OrderEventOut,
  type OrderStatus,
  STATUS_LABEL,
  STATUS_TONE,
} from "./types";

export function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const orderId = params.id ?? "";

  const orderQuery = useQuery<OrderAdminOut>({
    queryKey: qk.order(orderId),
    enabled: Boolean(orderId),
    queryFn: () => apiGet<OrderAdminOut>(`/api/v1/admin/orders/${orderId}`),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (!s) return false;
      if (["pending_payment", "paid", "fulfilling", "fulfilled"].includes(s)) {
        return 5_000;
      }
      return false;
    },
  });

  const paymentsQuery = useQuery<PaymentAdminListOut>({
    queryKey: ["admin", "payments", { orderId }],
    enabled: Boolean(orderId),
    queryFn: () =>
      apiGet<PaymentAdminListOut>(
        `/api/v1/admin/payments?order_id=${orderId}`,
      ),
  });

  const tasksQuery = useQuery<TaskListOut>({
    queryKey: ["admin", "fulfillment", { orderId }],
    enabled: Boolean(orderId),
    queryFn: () =>
      apiGet<TaskListOut>(
        `/api/v1/admin/fulfillment/tasks?order_id=${orderId}&limit=50`,
      ),
  });

  const cancel = useMutation<OrderAdminOut, ApiError, void>({
    mutationFn: () =>
      apiPost<OrderAdminOut>(`/api/v1/admin/orders/${orderId}/cancel`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
    },
  });

  const refund = useMutation<
    PaymentAdminOut,
    ApiError,
    { id: string; reason: string }
  >({
    mutationFn: ({ id, reason }) =>
      apiPost<PaymentAdminOut>(`/api/v1/admin/payments/${id}/refund`, {
        reason,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
      void qc.invalidateQueries({ queryKey: ["admin", "payments"] });
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
    },
  });

  if (orderQuery.isLoading) {
    return <Spinner label="Загрузка…" />;
  }
  if (orderQuery.isError || !orderQuery.data) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-[--color-danger]">
          Не удалось загрузить заказ.
        </p>
        <Button variant="ghost" onClick={() => navigate("/orders")}>
          <ArrowLeft className="size-4" />
          К списку
        </Button>
      </div>
    );
  }

  const order = orderQuery.data;
  const payments = paymentsQuery.data?.items ?? [];
  const tasks = tasksQuery.data?.items ?? [];

  return (
    <div>
      <PageHeader
        title={`Заказ ${order.id.slice(0, 8)}…`}
        description={
          order.user_id ? (
            <>
              Пользователь{" "}
              <Link
                to={`/customers/${order.user_id}`}
                className="font-mono text-[--color-fg] underline-offset-2 hover:underline"
              >
                {order.user_id.slice(0, 8)}…
              </Link>
            </>
          ) : (
            order.guest_email ?? "Гость"
          )
        }
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate("/orders")}>
              <ArrowLeft className="size-4" />К списку
            </Button>
            {order.status === "pending_payment" && (
              <Button
                variant="danger"
                onClick={() => {
                  if (confirm("Отменить заказ?")) cancel.mutate();
                }}
                disabled={cancel.isPending}
              >
                <Ban className="size-4" />
                {cancel.isPending ? "Отменяем…" : "Отменить"}
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ----- left column: summary + timeline ----- */}
        <section className="lg:col-span-2 space-y-6">
          <SummaryCard order={order} />
          <ItemsCard order={order} />
          <Timeline events={order.events} status={order.status} />
        </section>

        {/* ----- right column: payments + fulfillment ----- */}
        <aside className="space-y-6">
          <PaymentsCard
            payments={payments}
            refunding={refund.isPending}
            onRefund={(p) => {
              const reason = window.prompt(
                `Возврат ${Number.parseFloat(p.amount).toFixed(2)} ${p.currency} (${p.provider}). Причина:`,
                "",
              );
              if (reason === null) return;
              refund.mutate({ id: p.id, reason: reason.trim() });
            }}
          />
          <FulfillmentCard tasks={tasks} />
        </aside>
      </div>
    </div>
  );
}

function SummaryCard({ order }: { order: OrderAdminOut }) {
  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: "Статус",
      value: <StatusBadge status={order.status} />,
    },
    {
      label: "Сумма",
      value: (
        <span className="font-medium">
          {Number.parseFloat(order.total_charged).toFixed(2)} {order.currency}
          {order.currency !== "USD" && (
            <span className="ml-2 text-[--color-muted] text-xs">
              ≈ ${Number.parseFloat(order.total_usd).toFixed(2)}
            </span>
          )}
        </span>
      ),
    },
    {
      label: "Создан",
      value: formatDate(order.created_at),
    },
    {
      label: "Истекает",
      value: formatDate(order.expires_at),
    },
    {
      label: "Оплачен",
      value: formatDate(order.paid_at),
    },
    {
      label: "Доставлен",
      value: formatDate(order.delivered_at),
    },
  ];
  return (
    <div className="rounded-lg border bg-[--color-bg] p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[--color-muted]">
        Сводка
      </h2>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between text-sm">
            <dt className="text-[--color-muted]">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ItemsCard({ order }: { order: OrderAdminOut }) {
  return (
    <div className="rounded-lg border bg-[--color-bg]">
      <header className="border-b px-4 py-3 flex items-center gap-2">
        <Package className="size-4 text-[--color-muted]" />
        <h2 className="text-sm font-semibold">Позиции ({order.items.length})</h2>
      </header>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-[--color-muted]">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Товар</th>
            <th className="px-3 py-2 text-center font-medium">Кол-во</th>
            <th className="px-3 py-2 text-right font-medium">Цена</th>
            <th className="px-3 py-2 text-left font-medium">Fulfilment</th>
            <th className="px-3 py-2 text-left font-medium">Supplier order</th>
          </tr>
        </thead>
        <tbody>
          {order.items.map((it) => {
            const d = it.display;
            const headline = d
              ? d.brand_name
                ? `${d.brand_name} · ${d.denomination ?? d.sku_code}`
                : `${d.product_name || d.product_slug} · ${d.denomination ?? d.sku_code}`
              : it.sku_id.slice(0, 8) + "…";
            const sub = d
              ? d.product_name && d.product_name !== d.brand_name
                ? d.product_name
                : null
              : null;
            return (
              <tr key={it.id} className="border-t">
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    {d?.image_url ? (
                      <img
                        src={d.image_url}
                        alt=""
                        className="size-10 rounded-md object-cover border border-[--color-border] flex-shrink-0"
                      />
                    ) : (
                      <div
                        className="size-10 rounded-md flex items-center justify-center text-xs font-bold text-[--color-muted] border border-[--color-border] flex-shrink-0"
                        style={{ background: "var(--color-subtle)" }}
                      >
                        {(d?.brand_name?.[0] ?? "?").toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="font-medium truncate">{headline}</div>
                      <div className="flex items-center gap-1.5 text-xs text-[--color-muted] truncate">
                        {sub && <span>{sub}</span>}
                        {d?.region && d.region !== "GLOBAL" && (
                          <span className="rounded bg-[--color-subtle] px-1 font-mono">
                            {d.region}
                          </span>
                        )}
                        {d && (
                          <code className="text-[10px] opacity-70">
                            {d.sku_code}
                          </code>
                        )}
                      </div>
                      {Object.keys(it.fulfillment_data).length > 0 && (
                        <pre className="mt-1 text-[10px] text-[--color-muted] whitespace-pre-wrap break-all">
                          {JSON.stringify(it.fulfillment_data, null, 0)}
                        </pre>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-center font-mono">{it.qty}</td>
                <td className="px-3 py-2.5 text-right font-mono">
                  ${Number.parseFloat(it.unit_price_usd).toFixed(2)}
                </td>
                <td className="px-3 py-2.5">
                  <code className="text-xs">{it.fulfillment_state}</code>
                </td>
                <td className="px-3 py-2.5">
                  {it.supplier_order_id ? (
                    <code className="text-xs">
                      {it.supplier_order_id.slice(0, 12)}…
                    </code>
                  ) : (
                    <span className="text-xs text-[--color-muted]">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({
  events,
  status,
}: {
  events: OrderEventOut[];
  status: OrderStatus;
}) {
  const ordered = [...events].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  return (
    <div className="rounded-lg border bg-[--color-bg]">
      <header className="border-b px-4 py-3 flex items-center gap-2">
        <Clock className="size-4 text-[--color-muted]" />
        <h2 className="text-sm font-semibold">Хронология ({ordered.length})</h2>
      </header>
      {ordered.length === 0 ? (
        <p className="p-4 text-sm text-[--color-muted]">Событий ещё нет.</p>
      ) : (
        <ol className="relative space-y-4 p-4 pl-10">
          <span
            className="absolute left-5 top-6 bottom-6 w-px bg-[--color-border]"
            aria-hidden
          />
          {ordered.map((ev, idx) => (
            <li key={`${ev.created_at}-${idx}`} className="relative">
              <span
                className="absolute -left-6 top-1 inline-flex size-3 rounded-full ring-2 ring-[--color-bg]"
                style={{
                  background:
                    ev.kind === "order.paid"
                      ? "var(--color-success)"
                      : ev.kind === "order.delivered"
                        ? "var(--color-brand)"
                        : ev.kind.startsWith("payment.")
                          ? "var(--color-fg)"
                          : "var(--color-muted)",
                }}
              />
              <div className="flex items-baseline justify-between gap-3">
                <code className="text-sm font-semibold">{ev.kind}</code>
                <span className="text-xs text-[--color-muted]">
                  {formatDate(ev.created_at)}
                </span>
              </div>
              {ev.actor && (
                <p className="text-xs text-[--color-muted] mt-0.5">
                  by {ev.actor}
                </p>
              )}
              {Object.keys(ev.payload).length > 0 && (
                <pre className="mt-1 whitespace-pre-wrap rounded border bg-[--color-subtle] p-2 text-[10px] text-[--color-muted]">
                  {JSON.stringify(ev.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
      <footer className="border-t px-4 py-2 text-xs text-[--color-muted] flex items-center gap-2">
        <CircleDot className="size-3" />
        Текущий статус: <StatusBadge status={status} />
      </footer>
    </div>
  );
}

function PaymentsCard({
  payments,
  onRefund,
  refunding,
}: {
  payments: PaymentAdminOut[];
  onRefund: (payment: PaymentAdminOut) => void;
  refunding: boolean;
}) {
  return (
    <div className="rounded-lg border bg-[--color-bg]">
      <header className="border-b px-4 py-3 flex items-center gap-2">
        <CreditCard className="size-4 text-[--color-muted]" />
        <h2 className="text-sm font-semibold">
          Платежи ({payments.length})
        </h2>
      </header>
      {payments.length === 0 ? (
        <p className="p-4 text-sm text-[--color-muted]">
          Платежей по заказу пока нет.
        </p>
      ) : (
        <ul className="divide-y">
          {payments.map((p) => {
            const canRefund =
              p.status === "succeeded" || p.status === "partially_refunded";
            return (
              <li key={p.id} className="p-3 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <code className="text-xs">{p.id.slice(0, 8)}…</code>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      p.status === "succeeded"
                        ? "bg-[--success-soft] text-[--success-fg]"
                        : p.status === "failed"
                          ? "bg-[--danger-soft] text-[--danger-fg]"
                          : p.status === "refunded" ||
                              p.status === "partially_refunded"
                            ? "bg-[--info-soft] text-[--info-fg]"
                            : "bg-[--warning-soft] text-[--warning-fg]"
                    }`}
                  >
                    {p.status}
                  </span>
                </div>
                <p className="mt-1 text-xs text-[--color-muted]">
                  {p.provider} · {Number.parseFloat(p.amount).toFixed(2)}{" "}
                  {p.currency}
                </p>
                {p.intent_url && p.provider === "mock" && (
                  <p className="mt-1 text-[10px] text-[--color-muted] break-all">
                    {p.intent_url}
                  </p>
                )}
                {canRefund && (
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    onClick={() => onRefund(p)}
                    disabled={refunding}
                    className="mt-2"
                  >
                    Возврат
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function FulfillmentCard({ tasks }: { tasks: TaskAdminOut[] }) {
  return (
    <div className="rounded-lg border bg-[--color-bg]">
      <header className="border-b px-4 py-3 flex items-center gap-2">
        <Truck className="size-4 text-[--color-muted]" />
        <h2 className="text-sm font-semibold">Фулфилмент ({tasks.length})</h2>
      </header>
      {tasks.length === 0 ? (
        <p className="p-4 text-sm text-[--color-muted]">
          Задач саги ещё не запущено.
        </p>
      ) : (
        <ul className="divide-y">
          {tasks.map((t) => (
            <li key={t.id} className="p-3 text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <code className="text-xs">{t.supplier}</code>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    t.status === "succeeded"
                      ? "bg-[--success-soft] text-[--success-fg]"
                      : t.status === "failed"
                        ? "bg-[--danger-soft] text-[--danger-fg]"
                        : t.status === "cancelled"
                          ? "bg-[--bg-muted] text-[--text-secondary]"
                          : "bg-[--warning-soft] text-[--warning-fg]"
                  }`}
                >
                  {t.status}
                </span>
              </div>
              <p className="mt-1 text-xs text-[--color-muted]">
                item {t.order_item_id.slice(0, 8)}… · попыток {t.attempts_count}
              </p>
              {t.last_error && (
                <p className="mt-1 text-xs text-[--color-danger]">
                  {t.last_error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
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

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Tiny visual import — kept for tree-shaking-friendly icon set.
const _icons = { Coins, Check };
void _icons;
