"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

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
  const t = useTranslations("web.orders");
  // Guest identification travels as a header, never a query param — a query
  // param lands in Caddy / proxy access logs and browser history, a header
  // doesn't. Trimmed + lowercased to match what the backend expects.
  const guestHeaders = email ? { "X-Guest-Email": email.trim().toLowerCase() } : {};

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}`, { headers: guestHeaders }),
    refetchInterval: (q) => (q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false),
  });

  const status = order.data?.status;

  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: status === "delivered",
    queryFn: () =>
      apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries`, { headers: guestHeaders }),
  });

  if (order.isLoading) return <p className="text-tx-mute">{t("loading")}</p>;
  if (order.isError || !order.data) return <p className="text-[#FF6B6B]">{t("notFound")}</p>;

  return (
    <div className="border-border bg-card rounded-2xl border p-6">
      <p className="text-tx-dim font-mono text-xs">#{order.data.id.slice(0, 8)}</p>
      <h2 className="font-display mt-2 text-xl font-bold">
        {KNOWN_STATUSES.has(order.data.status)
          ? t(`status.${order.data.status}`)
          : order.data.status}
      </h2>

      {status === "delivered" &&
        deliveries.data?.items.map((d) => (
          <pre key={d.id} className="bg-muted mt-4 overflow-x-auto rounded-lg p-3 text-sm">
            {JSON.stringify(d.artifact, null, 2)}
          </pre>
        ))}
    </div>
  );
}

/** Statuses with a ``web.orders.status.*`` catalog entry; raw codes fall through. */
const KNOWN_STATUSES = new Set([
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
  "delivered",
  "failed",
  "refunded",
  "partially_refunded",
  "cancelled",
  "expired",
]);
