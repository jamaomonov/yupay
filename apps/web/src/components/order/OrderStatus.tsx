"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ArtifactReceipt } from "./ArtifactReceipt";
import { GuestReviewPanel } from "./GuestReviewPanel";
import { OrderItems } from "./OrderItems";
import { OrderSummary } from "./OrderSummary";
import { StatusBlock } from "./StatusBlock";

import type { OrderOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { getMyReviews } from "@/lib/reviews";
import { pathFor } from "@/lib/seo";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

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
  const tr = useTranslations("web.brandReviews");
  const locale = useLocale();
  const { user } = useAuth();
  // Guest identification travels as a header, never a query param — a query
  // param lands in Caddy / proxy access logs and browser history, a header
  // doesn't. Trimmed + lowercased to match what the backend expects.
  const guestHeaders = email ? { "X-Guest-Email": email.trim().toLowerCase() } : {};
  // While the WS is connected, live pushes keep the cache fresh — invalidated
  // messages already trigger a refetch, so polling is redundant. Polling is
  // the fallback for guests, disconnected sockets, and the reconnect window.
  const connected = useRealtimeStatus((s) => s.connected);

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}`, { headers: guestHeaders }),
    refetchInterval: (q) =>
      !connected && q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false,
  });

  const status = order.data?.status;

  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: status === "delivered",
    queryFn: () =>
      apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries`, { headers: guestHeaders }),
  });

  // Fallback rate CTA: even if the delivered modal was skipped or missed, a
  // logged-in buyer who hasn't reviewed this order can rate it from here. Guests
  // can't review, so the query only runs for a signed-in user on a delivered order.
  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: Boolean(user) && status === "delivered",
  });

  if (order.isLoading) return <p className="text-tx-mute">{t("loading")}</p>;
  if (order.isError || !order.data) return <p className="text-[#FF6B6B]">{t("notFound")}</p>;

  const brandSlug = order.data.items[0]?.display?.brand_slug ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === order.data.id);
  const canRate = status === "delivered" && Boolean(user) && brandSlug !== null && !alreadyReviewed;

  return (
    <div className="border-border bg-card rounded-2xl border p-6">
      <p className="text-tx-dim font-mono text-xs">#{order.data.id.slice(0, 8)}</p>
      <div className="mt-2">
        <StatusBlock status={order.data.status} />
      </div>

      <div className="mt-4">
        <OrderSummary order={order.data} />
      </div>

      <div className="mt-4">
        <OrderItems items={order.data.items} />
      </div>

      {status === "delivered" &&
        deliveries.data?.items.map((d) => <ArtifactReceipt key={d.id} artifact={d.artifact} />)}

      {canRate && brandSlug && (
        <Link
          href={pathFor(locale, `/store/${brandSlug}?order=${order.data.id}#reviews`)}
          className={buttonStyles({ size: "sm", className: "mt-4" })}
        >
          {tr("writeCta")}
        </Link>
      )}

      {status === "delivered" && !user && email && brandSlug && (
        <GuestReviewPanel orderId={order.data.id} email={email} />
      )}
    </div>
  );
}
