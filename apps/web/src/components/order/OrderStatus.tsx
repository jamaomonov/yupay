"use client";

import { useQuery } from "@tanstack/react-query";

import type { OrderOut } from "@/lib/orders-types";

import { apiFetch } from "@/lib/client";

/** Statuses that mean the order is still moving — keep polling. */
const IN_MOTION = new Set(["pending_payment", "paid", "fulfilling", "fulfilled"]);

interface DeliveryOut {
  id: string;
  order_item_id: string;
  channel: string;
  artifact_kind: string;
  artifact: Record<string, unknown>;
  delivered_at: string;
}

interface DeliveryListOut {
  items: DeliveryOut[];
}

export function OrderStatus({ orderId, email }: { orderId: string; email?: string }) {
  const suffix = email ? `?email=${encodeURIComponent(email)}` : "";

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}${suffix}`),
    refetchInterval: (q) => (q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false),
  });

  const status = order.data?.status;

  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: status === "delivered",
    queryFn: () => apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries${suffix}`),
  });

  if (order.isLoading) return <p className="text-tx-mute">Загрузка…</p>;
  if (order.isError || !order.data) return <p className="text-[#FF6B6B]">Заказ не найден.</p>;

  return (
    <div className="border-border bg-card rounded-2xl border p-6">
      <p className="text-tx-dim font-mono text-xs">#{order.data.id.slice(0, 8)}</p>
      <h2 className="font-display mt-2 text-xl font-bold">{statusLabel(order.data.status)}</h2>

      {status === "delivered" &&
        deliveries.data?.items.map((d) => (
          <pre key={d.id} className="bg-muted mt-4 overflow-x-auto rounded-lg p-3 text-sm">
            {JSON.stringify(d.artifact, null, 2)}
          </pre>
        ))}
    </div>
  );
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending_payment: "Ожидает оплаты",
    paid: "Оплачено",
    fulfilling: "Выполняется",
    fulfilled: "Готово",
    delivered: "Доставлено",
    failed: "Ошибка",
    refunded: "Возврат",
    partially_refunded: "Частичный возврат",
    cancelled: "Отменён",
    expired: "Истёк",
  };
  return map[s] ?? s;
}
