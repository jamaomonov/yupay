import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import {
  ArrowLeft,
  Ban,
  Check,
  CircleDot,
  Clock,
  Coins,
  CreditCard,
  AlertTriangle,
  CheckCircle2,
  Eye,
  KeyRound,
  Mail,
  Package,
  PackageCheck,
  RefreshCw,
  Truck,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { EvidenceCard } from "./EvidenceCard";
import {
  type EvidencePackOut,
  type OrderAdminOut,
  type OrderEventOut,
  type OrderStatus,
  STATUS_LABEL,
  STATUS_TONE,
} from "./types";

import type { DeliveryListOut, TaskAdminOut, TaskListOut } from "@/features/fulfillment/types";
import type { PaymentAdminListOut, PaymentAdminOut } from "@/features/payments/types";

import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { CopyId } from "@/components/CopyId";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { StatusChip } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { ForceCompleteModal } from "@/features/fulfillment/ForceCompleteModal";
import {
  STATUS_LABEL as PAYMENT_STATUS_LABEL,
  STATUS_TONE as PAYMENT_STATUS_TONE,
} from "@/features/payments/types";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { formatMoney, formatMoneyValue } from "@/lib/money";
import { qk } from "@/lib/queryKeys";

/** Statuses where "close as failed" is offered — mirrors the server guard
 *  (`orders.service._FAILABLE_STATUSES`): money in, goods not out. */
const FAILABLE = new Set<OrderStatus>(["paid", "fulfilling", "fulfilled"]);

export function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const orderId = params.id ?? "";
  const [manualDeliverFor, setManualDeliverFor] = useState<TaskAdminOut | null>(null);
  // Codes stay hidden until the operator asks: they are bearer instruments, the
  // fetch is what gets audited server-side, and nobody wants them on screen
  // during a screen-share.
  const [codesRevealed, setCodesRevealed] = useState(false);
  // Same bargain for the buyer's IP and browser: personal data, audited read.
  const [evidenceRevealed, setEvidenceRevealed] = useState(false);
  const toast = useToast();

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
    queryFn: () => apiGet<PaymentAdminListOut>(`/api/v1/admin/payments?order_id=${orderId}`),
  });

  const tasksQuery = useQuery<TaskListOut>({
    queryKey: ["admin", "fulfillment", { orderId }],
    enabled: Boolean(orderId),
    queryFn: () =>
      apiGet<TaskListOut>(`/api/v1/admin/fulfillment/tasks?order_id=${orderId}&limit=50`),
  });

  const deliveriesQuery = useQuery<DeliveryListOut>({
    queryKey: ["admin", "orders", orderId, "deliveries"],
    enabled: codesRevealed,
    // Every fetch writes an audit event server-side, so don't re-poll silently.
    staleTime: Infinity,
    queryFn: () => apiGet<DeliveryListOut>(`/api/v1/admin/orders/${orderId}/deliveries`),
  });

  const evidenceQuery = useQuery<EvidencePackOut>({
    queryKey: ["admin", "orders", orderId, "evidence"],
    enabled: evidenceRevealed,
    // Every fetch writes an audit event server-side, so don't re-poll silently.
    staleTime: Infinity,
    queryFn: () => apiGet<EvidencePackOut>(`/api/v1/admin/orders/${orderId}/evidence`),
  });

  const resendEmail = useMutation<void, ApiError>({
    mutationFn: async () => {
      await apiPost(`/api/v1/admin/orders/${orderId}/resend-delivery-email`, {});
    },
    onSuccess: () => {
      toast.success("Письмо с выдачей отправлено на адрес заказа");
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  // Manual settlement asserts "money arrived" without a provider saying so, so
  // the operator has to supply the acquirer's own transaction id as evidence.
  const [settleFor, setSettleFor] = useState<PaymentAdminOut | null>(null);
  const [settleReason, setSettleReason] = useState("");
  const [settleRef, setSettleRef] = useState("");
  const settleIdemRef = useRef<string>("");

  const settle = useMutation<PaymentAdminOut, ApiError, { id: string }>({
    mutationFn: ({ id }) =>
      apiPost<PaymentAdminOut>(
        `/api/v1/admin/payments/${id}/settle`,
        { reason: settleReason.trim(), provider_reference: settleRef.trim() },
        { "Idempotency-Key": settleIdemRef.current },
      ),
    onSuccess: () => {
      setSettleFor(null);
      setSettleReason("");
      setSettleRef("");
      toast.success("Платёж отмечен оплаченным, выдача запущена");
      void qc.invalidateQueries({ queryKey: ["admin", "payments"] });
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const cancel = useMutation<OrderAdminOut, ApiError>({
    mutationFn: () => apiPost<OrderAdminOut>(`/api/v1/admin/orders/${orderId}/cancel`, {}),
    onSuccess: () => {
      toast.success("Заказ отменён");
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const refund = useMutation<PaymentAdminOut, ApiError, { id: string; reason: string }>({
    mutationFn: ({ id, reason }) =>
      apiPost<PaymentAdminOut>(
        `/api/v1/admin/payments/${id}/refund`,
        { reason },
        { "Idempotency-Key": crypto.randomUUID() },
      ),
    onSuccess: () => {
      toast.success("Возврат оформлен");
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
      void qc.invalidateQueries({ queryKey: ["admin", "payments"] });
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  // Close a paid order that can't be delivered. The server refuses this before
  // payment (use cancel) and after delivery (use refund), and cancels open
  // fulfilment tasks so a failed order can't still hand out codes.
  const markFailed = useMutation<OrderAdminOut, ApiError, string>({
    mutationFn: (reason) =>
      apiPost<OrderAdminOut>(`/api/v1/admin/orders/${orderId}/fail`, { reason }),
    onSuccess: () => {
      toast.success("Заказ закрыт как проблемный");
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  // Release an order the risk rules held before fulfilment ever started
  // (ADR-0047). This is the same call the payment webhook would have made had
  // the order not been held, so nothing has to be undone — the hold is the
  // absence of this call, not a state to reverse. `start_for_order` is
  // idempotent, so a double click cannot deliver twice.
  const [confirmRelease, setConfirmRelease] = useState(false);

  const release = useMutation<TaskListOut, ApiError>({
    mutationFn: () =>
      apiPost<TaskListOut>(`/api/v1/admin/fulfillment/orders/${orderId}/release`, {}),
    onSuccess: () => {
      setConfirmRelease(false);
      toast.success("Выдача запущена");
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  // Re-run a stuck/failed supplier task in place — the first thing to try when
  // an order is stuck in `fulfilling`, and previously only reachable from the
  // separate Fulfilment screen.
  const retryTask = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (taskId) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${taskId}/retry`, {}),
    onSuccess: () => {
      toast.success("Задача отправлена на повтор");
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
      void qc.invalidateQueries({ queryKey: qk.order(orderId) });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  if (orderQuery.isLoading) {
    return <Spinner label="Загрузка…" />;
  }
  if (orderQuery.isError || !orderQuery.data) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-[var(--danger)]">Не удалось загрузить заказ.</p>
        <Button variant="ghost" onClick={() => navigate("/orders")}>
          <ArrowLeft className="size-4" />К списку
        </Button>
      </div>
    );
  }

  const order = orderQuery.data;
  const payments = paymentsQuery.data?.items ?? [];
  const tasks = tasksQuery.data?.items ?? [];

  // A held order deliberately keeps status `paid` and grows no fulfilment task
  // (ADR-0047), so it is invisible on the Fulfilment screen and indistinguishable
  // from a just-paid one by status alone — the event is the only marker. Tasks
  // existing means it was already released, so the banner retires itself.
  const heldForReview =
    order.status === "paid" &&
    tasks.length === 0 &&
    order.events.some((e) => e.kind === "order.held_for_review");

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Заказы", to: "/orders" }, { label: `${order.id.slice(0, 8)}…` }]}
        title={`Заказ ${order.id.slice(0, 8)}…`}
        description={
          // The order id belongs here rather than only in the (string-typed)
          // title: this is the id support pastes into a provider console or a
          // ticket, so it has to be copyable in one click.
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <CopyId value={order.id} chars={13} label="id" className="text-xs" />
            {order.user_id ? (
              <span>
                Пользователь{" "}
                <Link
                  to={`/customers/${order.user_id}`}
                  title={order.user_id}
                  className="font-mono text-[var(--text-primary)] underline-offset-2 hover:underline"
                >
                  {order.user_id.slice(0, 8)}…
                </Link>
              </span>
            ) : (
              <span>{order.guest_email ?? "Гость"}</span>
            )}
          </span>
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
            {/* Paid but undeliverable. Not offered on `delivered` — the customer
                already has the goods, so the correct reversal is a refund. */}
            {FAILABLE.has(order.status) && (
              <Button
                variant="danger"
                onClick={() => {
                  const reason = prompt(
                    "Почему заказ не может быть выполнен?\n" +
                      "Причина попадёт в историю заказа. Деньги НЕ возвращаются — " +
                      "для возврата используйте «Вернуть» в блоке платежей.",
                  );
                  if (reason && reason.trim().length >= 3) markFailed.mutate(reason.trim());
                }}
                disabled={markFailed.isPending}
              >
                <AlertTriangle className="size-4" />
                {markFailed.isPending ? "Закрываем…" : "Отметить проблемным"}
              </Button>
            )}
          </>
        }
      />

      {/* The whole point of the hold is that a human looks before the goods
          leave, so this sits above the fold rather than as one more button in
          the header: the operator arrives here from a Telegram alert and needs
          to see *why* nothing happened, not hunt for the release. */}
      {heldForReview && (
        <div
          role="alert"
          className="border-[var(--warning-fg)]/40 mb-6 flex flex-wrap items-start gap-3 rounded-lg border bg-[var(--warning-soft)] p-4"
        >
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-[var(--warning-fg)]" />
          <div className="min-w-[16rem] flex-1">
            <h2 className="text-sm font-semibold text-[var(--warning-fg)]">
              Заказ на проверке — выдача не запускалась
            </h2>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Оплата прошла, но сумма не ниже порога ручной проверки, поэтому товар автоматически не
              выдан. Проверьте плательщика, затем выдайте товар — или верните деньги в блоке
              платежей.
            </p>
          </div>
          <Button
            onClick={() => {
              setConfirmRelease(true);
            }}
            disabled={release.isPending}
          >
            <PackageCheck className="size-4" />
            {release.isPending ? "Запускаем…" : "Выдать"}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ----- left column: summary + timeline ----- */}
        <section className="space-y-6 lg:col-span-2">
          <SummaryCard order={order} />
          <ItemsCard order={order} />
          <Timeline events={order.events} status={order.status} orderId={order.id} />
        </section>

        {/* ----- right column: payments + fulfillment ----- */}
        <aside className="space-y-6">
          <PaymentsCard
            payments={payments}
            orderId={order.id}
            failed={paymentsQuery.isError}
            onRetryLoad={() => void paymentsQuery.refetch()}
            refunding={refund.isPending}
            settling={settle.isPending}
            onSettle={(p) => {
              // One key per opened dialog — a double-click on confirm must not
              // settle twice.
              settleIdemRef.current = `admin-settle-${crypto.randomUUID()}`;
              setSettleReason("");
              setSettleRef("");
              setSettleFor(p);
            }}
            onRefund={(p) => {
              const reason = window.prompt(
                `Возврат ${formatMoney(p.amount, p.currency)} (${p.provider}). Причина:`,
                "",
              );
              if (reason === null) return;
              refund.mutate({ id: p.id, reason: reason.trim() });
            }}
          />
          <DeliveriesCard
            revealed={codesRevealed}
            onReveal={() => {
              setCodesRevealed(true);
            }}
            query={deliveriesQuery}
            onResend={() => {
              resendEmail.mutate();
            }}
            resending={resendEmail.isPending}
            canResend={Boolean(order.guest_email)}
          />
          <EvidenceCard
            revealed={evidenceRevealed}
            onReveal={() => {
              setEvidenceRevealed(true);
            }}
            query={evidenceQuery}
          />
          <FulfillmentCard
            tasks={tasks}
            onRetry={(taskId) => {
              retryTask.mutate(taskId);
            }}
            onManualDeliver={setManualDeliverFor}
            retryingId={retryTask.isPending ? retryTask.variables : null}
            failed={tasksQuery.isError}
            onRetryLoad={() => void tasksQuery.refetch()}
          />
        </aside>
      </div>

      {settleFor && (
        <ConfirmDialog
          title="Отметить платёж оплаченным?"
          tone="danger"
          confirmLabel="Отметить оплаченным"
          busy={settle.isPending}
          onCancel={() => {
            setSettleFor(null);
          }}
          onConfirm={() => {
            if (settleReason.trim().length < 3 || settleRef.trim().length < 3) return;
            settle.mutate({ id: settleFor.id });
          }}
        >
          <p>
            Это утверждает, что деньги пришли, <strong>без подтверждения провайдера</strong>, и
            запускает выдачу товара. Указывайте номер транзакции из консоли эквайера — он попадёт в
            историю заказа.
          </p>
          <label className="mt-3 block text-xs uppercase text-[var(--text-secondary)]">
            Номер транзакции у провайдера
            <input
              value={settleRef}
              onChange={(e) => {
                setSettleRef(e.target.value);
              }}
              placeholder="например: CLICK-99887"
              className="mt-1 h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm text-[var(--text-primary)]"
            />
          </label>
          <label className="mt-2 block text-xs uppercase text-[var(--text-secondary)]">
            Причина
            <input
              value={settleReason}
              onChange={(e) => {
                setSettleReason(e.target.value);
              }}
              placeholder="вебхук не дошёл, оплата видна в консоли"
              className="mt-1 h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm text-[var(--text-primary)]"
            />
          </label>
        </ConfirmDialog>
      )}

      {confirmRelease && (
        <ConfirmDialog
          title="Запустить выдачу?"
          tone="danger"
          confirmLabel="Выдать"
          busy={release.isPending}
          onCancel={() => {
            setConfirmRelease(false);
          }}
          onConfirm={() => {
            release.mutate();
          }}
        >
          <p>
            Товар уйдёт покупателю, и <strong>отменить выдачу уже нельзя</strong> — вернуть можно
            будет только деньги. Убедитесь, что плательщик проверен.
          </p>
        </ConfirmDialog>
      )}

      {/* Attaches a real Delivery (codes / receipt) and walks the order to
          `delivered` — the safe counterpart to a manual status change. */}
      {manualDeliverFor && (
        <ForceCompleteModal
          task={manualDeliverFor}
          onClose={() => {
            setManualDeliverFor(null);
          }}
          onCompleted={() => {
            setManualDeliverFor(null);
            void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
            void qc.invalidateQueries({ queryKey: qk.order(orderId) });
          }}
        />
      )}
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
          {formatMoney(order.total_charged, order.currency)}
          {/* `charged_usd`, not `total_usd`: on a Steam top-up the latter is
              the face value the buyer picked ($10 of credit), so showing it
              here read as "134 380 сум ≈ $10" — off by the entire markup. */}
          {order.currency !== "USD" && order.charged_usd !== null && (
            <span className="ml-2 text-xs text-[var(--text-secondary)]">
              ≈ ${formatMoneyValue(order.charged_usd, "USD")}
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
    <div className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Сводка
      </h2>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between text-sm">
            <dt className="text-[var(--text-secondary)]">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ItemsCard({ order }: { order: OrderAdminOut }) {
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Package className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Позиции ({order.items.length})</h2>
      </header>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-[var(--text-secondary)]">
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
                        className="size-10 flex-shrink-0 rounded-md border border-[var(--border-default)] object-cover"
                      />
                    ) : (
                      <div
                        className="flex size-10 flex-shrink-0 items-center justify-center rounded-md border border-[var(--border-default)] text-xs font-bold text-[var(--text-secondary)]"
                        style={{ background: "var(--bg-muted)" }}
                      >
                        {(d?.brand_name?.[0] ?? "?").toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="truncate font-medium">{headline}</div>
                      <div className="flex items-center gap-1.5 truncate text-xs text-[var(--text-secondary)]">
                        {sub && <span>{sub}</span>}
                        {d?.region && d.region !== "GLOBAL" && (
                          <span className="rounded bg-[var(--bg-muted)] px-1 font-mono">
                            {d.region}
                          </span>
                        )}
                        {d && <code className="text-[10px] opacity-70">{d.sku_code}</code>}
                      </div>
                      {Object.keys(it.fulfillment_data).length > 0 && (
                        <pre className="mt-1 whitespace-pre-wrap break-all text-[10px] text-[var(--text-secondary)]">
                          {JSON.stringify(it.fulfillment_data, null, 0)}
                        </pre>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-center font-mono">{it.qty}</td>
                <td className="px-3 py-2.5 text-right font-mono">
                  ${formatMoneyValue(it.unit_price_usd, "USD")}
                </td>
                <td className="px-3 py-2.5">
                  <StatusChip domain="fulfillmentState" value={it.fulfillment_state} />
                </td>
                <td className="px-3 py-2.5">
                  {it.supplier_order_id ? (
                    <code className="text-xs">{it.supplier_order_id.slice(0, 12)}…</code>
                  ) : (
                    <span className="text-xs text-[var(--text-secondary)]">—</span>
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
  orderId,
}: {
  events: OrderEventOut[];
  status: OrderStatus;
  orderId: string;
}) {
  const ordered = [...events].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Clock className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Хронология ({ordered.length})</h2>
        {/* The order's own events; the audit feed also carries the payment,
            webhook and fulfilment events that reference this id. */}
        <Link
          to={`/audit?target=${orderId}`}
          className="ml-auto text-xs text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
        >
          Полный аудит →
        </Link>
      </header>
      {ordered.length === 0 ? (
        <p className="p-4 text-sm text-[var(--text-secondary)]">Событий ещё нет.</p>
      ) : (
        <ol className="relative space-y-4 p-4 pl-10">
          <span
            className="absolute bottom-6 left-5 top-6 w-px bg-[var(--color-border)]"
            aria-hidden
          />
          {ordered.map((ev, idx) => (
            <li key={`${ev.created_at}-${idx}`} className="relative">
              <span
                className="absolute -left-6 top-1 inline-flex size-3 rounded-full ring-2 ring-[var(--color-bg)]"
                style={{
                  background:
                    ev.kind === "order.paid"
                      ? "var(--color-success)"
                      : ev.kind === "order.delivered"
                        ? "var(--accent)"
                        : ev.kind.startsWith("payment.")
                          ? "var(--text-primary)"
                          : "var(--text-secondary)",
                }}
              />
              <div className="flex items-baseline justify-between gap-3">
                <StatusChip domain="eventKind" value={ev.kind} />
                <span className="text-xs text-[var(--text-secondary)]">
                  {formatDate(ev.created_at)}
                </span>
              </div>
              {ev.actor && (
                <p className="mt-0.5 text-xs text-[var(--text-secondary)]">by {ev.actor}</p>
              )}
              {Object.keys(ev.payload).length > 0 && (
                <pre className="mt-1 whitespace-pre-wrap rounded border bg-[var(--bg-muted)] p-2 text-[10px] text-[var(--text-secondary)]">
                  {JSON.stringify(roundMoneyFields(ev.payload), null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
      <footer className="flex items-center gap-2 border-t px-4 py-2 text-xs text-[var(--text-secondary)]">
        <CircleDot className="size-3" />
        Текущий статус: <StatusBadge status={status} />
      </footer>
    </div>
  );
}

/**
 * What the customer actually received — the answer to "the code doesn't work".
 *
 * Codes are bearer instruments, so they are not rendered until the operator
 * clicks: the reveal is the moment the server records who looked
 * (`admin.deliveries_viewed`), and it keeps secrets off the screen during
 * screen-shares. "Отправить письмо повторно" re-mails the delivered email to
 * the order's own address (never an address typed here).
 */
function DeliveriesCard({
  revealed,
  onReveal,
  query,
  onResend,
  resending,
  canResend,
}: {
  revealed: boolean;
  onReveal: () => void;
  query: UseQueryResult<DeliveryListOut>;
  onResend: () => void;
  resending: boolean;
  canResend: boolean;
}) {
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <KeyRound className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Выдача</h2>
      </header>

      <div className="space-y-3 p-3 text-sm">
        {!revealed && (
          <>
            <p className="text-[var(--text-secondary)]">
              Коды скрыты. Просмотр записывается в историю заказа.
            </p>
            <Button variant="ghost" className="h-7 px-2 text-xs" onClick={onReveal}>
              <Eye className="size-3.5" />
              Показать выдачу
            </Button>
          </>
        )}

        {revealed && query.isLoading && <p className="text-[var(--text-secondary)]">Загружаем…</p>}

        {revealed && query.isError && (
          <CardLoadError onRetry={() => void query.refetch()} what="выдачу" />
        )}

        {revealed && query.data?.items.length === 0 && (
          <p className="text-[var(--text-secondary)]">Пока ничего не выдано.</p>
        )}

        {revealed &&
          query.data?.items.map((d) => (
            <div key={d.id} className="rounded-md border border-[var(--border-default)] p-2.5">
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <code className="text-xs text-[var(--text-secondary)]">{d.artifact_kind}</code>
                <span className="text-xs text-[var(--text-secondary)]">
                  {new Date(d.delivered_at).toLocaleString("ru")}
                </span>
              </div>
              {/* The raw artifact: internal fields (source, upstream id) are
                  exactly what reconciliation with a supplier needs. */}
              <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs text-[var(--text-primary)]">
                {JSON.stringify(d.artifact, null, 2)}
              </pre>
            </div>
          ))}

        {canResend && (
          <Button
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={onResend}
            disabled={resending}
          >
            <Mail className="size-3.5" />
            {resending ? "Отправляем…" : "Отправить письмо повторно"}
          </Button>
        )}
      </div>
    </div>
  );
}

/** Compact in-card failure notice — a full ErrorState would dwarf these
 *  sidebar cards, but silence would read as "there is nothing here". */
function CardLoadError({ onRetry, what }: { onRetry?: (() => void) | undefined; what: string }) {
  return (
    <div role="alert" className="p-4 text-sm">
      <p className="text-[var(--danger)]">Не удалось загрузить {what}.</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 text-xs text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
        >
          Повторить
        </button>
      )}
    </div>
  );
}

function PaymentsCard({
  payments,
  orderId,
  onRefund,
  refunding,
  onSettle,
  settling,
  failed,
  onRetryLoad,
}: {
  payments: PaymentAdminOut[];
  orderId: string;
  onRefund: (payment: PaymentAdminOut) => void;
  refunding: boolean;
  onSettle: (payment: PaymentAdminOut) => void;
  settling: boolean;
  /** The payments query failed — "no payments" would be a lie mid-support-call. */
  failed?: boolean | undefined;
  onRetryLoad?: (() => void) | undefined;
}) {
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <CreditCard className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Платежи ({payments.length})</h2>
        {/* Attempts, webhooks and refunds live on the payments page; this card
            only summarises them. Support following a failed charge had to go
            there and paste the order id by hand. */}
        <Link
          to={`/payments?order_id=${orderId}`}
          className="ml-auto text-xs text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
        >
          В разделе платежей →
        </Link>
      </header>
      {failed ? (
        <CardLoadError onRetry={onRetryLoad} what="платежи" />
      ) : payments.length === 0 ? (
        <p className="p-4 text-sm text-[var(--text-secondary)]">Платежей по заказу пока нет.</p>
      ) : (
        <ul className="divide-y">
          {payments.map((p) => {
            const canRefund = p.status === "succeeded" || p.status === "partially_refunded";
            return (
              <li key={p.id} className="p-3 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <CopyId value={p.id} className="text-xs" />
                  <Badge tone={PAYMENT_STATUS_TONE[p.status]} dot>
                    {PAYMENT_STATUS_LABEL[p.status]}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {p.provider} · {formatMoney(p.amount, p.currency)}
                </p>
                {p.intent_url && p.provider === "mock" && (
                  <p className="mt-1 break-all text-[10px] text-[var(--text-secondary)]">
                    {p.intent_url}
                  </p>
                )}
                {canRefund && (
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      onRefund(p);
                    }}
                    disabled={refunding}
                    className="mt-2"
                  >
                    Возврат
                  </Button>
                )}
                {/* The acquirer charged but never called back — the order would
                    otherwise sit unpaid until it expires. */}
                {(p.status === "pending" || p.status === "requires_action") && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      onSettle(p);
                    }}
                    disabled={settling}
                    className="mt-2"
                  >
                    <CheckCircle2 className="size-3.5" />
                    Отметить оплаченным
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

/**
 * Fulfilment tasks for this order, with the two recovery actions inline.
 *
 * These used to live only on the separate Fulfilment screen, so fixing a stuck
 * order meant leaving the order you were looking at. Retry re-runs the supplier
 * call; "Выдать вручную" attaches a real artifact (codes / receipt) and walks
 * the order to `delivered` — that is the safe way to hand over goods by hand,
 * as opposed to flipping the order status, which would leave the customer on a
 * "delivered" order with nothing to show.
 */
function FulfillmentCard({
  tasks,
  onRetry,
  onManualDeliver,
  retryingId,
  failed,
  onRetryLoad,
}: {
  tasks: TaskAdminOut[];
  onRetry: (taskId: string) => void;
  onManualDeliver: (task: TaskAdminOut) => void;
  retryingId: string | null;
  /** The task query failed — do not claim the saga never started. */
  failed?: boolean | undefined;
  onRetryLoad?: (() => void) | undefined;
}) {
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Truck className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Фулфилмент ({tasks.length})</h2>
      </header>
      {failed ? (
        <CardLoadError onRetry={onRetryLoad} what="задачи" />
      ) : tasks.length === 0 ? (
        <p className="p-4 text-sm text-[var(--text-secondary)]">Задач саги ещё не запущено.</p>
      ) : (
        <ul className="divide-y">
          {tasks.map((t) => {
            const retryable = t.status === "failed" || t.status === "pending";
            const deliverable = t.status !== "succeeded" && t.status !== "cancelled";
            return (
              <li key={t.id} className="p-3 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <code className="text-xs">{t.supplier}</code>
                  <StatusChip domain="taskStatus" value={t.status} />
                </div>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  <CopyId value={t.order_item_id} label="item" className="text-xs" /> · попыток{" "}
                  {t.attempts_count}
                </p>
                {t.last_error && (
                  <p className="mt-1 text-xs text-[var(--danger)]">{t.last_error}</p>
                )}
                {(retryable || deliverable) && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {retryable && (
                      <Button
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => {
                          onRetry(t.id);
                        }}
                        disabled={retryingId === t.id}
                      >
                        <RefreshCw className="size-3.5" />
                        {retryingId === t.id ? "Повтор…" : "Повторить"}
                      </Button>
                    )}
                    {deliverable && (
                      <Button
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => {
                          onManualDeliver(t);
                        }}
                      >
                        <PackageCheck className="size-3.5" />
                        Выдать вручную
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: OrderStatus }) {
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

// Event payloads are raw audit JSON straight off the backend — money fields
// carry full NUMERIC(20,6) ledger precision (e.g. "total_charged":
// "12919.969152"). This is a debug/audit blob, not a money column with a
// known currency, so the full currency-aware `formatMoney` doesn't apply —
// just round decimal-looking numeric strings on money-ish keys to 2 places
// so raw ledger fractions never leak into the timeline.
const MONEY_ISH_KEY = /(amount|total|price|cost|balance|charged|_usd|_usdt)/i;
const DECIMAL_STRING = /^-?\d+\.\d+$/;

function roundMoneyFields(payload: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === "string" && MONEY_ISH_KEY.test(key) && DECIMAL_STRING.test(value)) {
      const n = Number.parseFloat(value);
      out[key] = Number.isFinite(n) ? n.toFixed(2) : value;
    } else {
      out[key] = value;
    }
  }
  return out;
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
