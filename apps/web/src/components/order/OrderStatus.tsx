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
import { mintGuestToken } from "@/lib/guest";
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
  // A guest is identified by the `?email=` query param and has no session. If
  // both are present (e.g. a logged-in user opened a guest link), the Bearer
  // session wins and the email is ignored — the logged-in path is unchanged.
  const isGuest = Boolean(email) && !user;
  const normalizedEmail = email?.trim().toLowerCase();

  // Guests carry no Bearer token, so the backend requires a short-lived
  // `Guest` token minted from the email (see /auth/guest). Cached by
  // react-query under the email key rather than per-render; a stale/expired
  // token gets re-minted the next time this query refetches (focus, retry).
  const guestToken = useQuery({
    queryKey: ["guest-token", normalizedEmail],
    enabled: isGuest,
    queryFn: () => {
      // `enabled: isGuest` guarantees `email` (and so `normalizedEmail`) is set
      // whenever this actually runs; the guard just satisfies the type checker.
      if (!normalizedEmail) throw new Error("guest order view: missing email");
      return mintGuestToken(normalizedEmail);
    },
  });
  // `anonymous: true` stops apiFetch from overwriting Authorization with a
  // stale/absent Bearer header — the explicit Guest header below survives.
  const guestAuth =
    isGuest && guestToken.data && normalizedEmail
      ? {
          anonymous: true as const,
          headers: {
            Authorization: `Guest ${guestToken.data}`,
            "X-Guest-Email": normalizedEmail,
          },
        }
      : undefined;
  // Guest fetches wait for the token; the logged-in (no email) path never blocks.
  const authReady = !isGuest || Boolean(guestAuth);

  // While the WS is connected, live pushes keep the cache fresh — invalidated
  // messages already trigger a refetch, so polling is redundant. Polling is
  // the fallback for guests, disconnected sockets, and the reconnect window.
  const connected = useRealtimeStatus((s) => s.connected);

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}`, guestAuth),
    enabled: authReady,
    refetchInterval: (q) =>
      !connected && q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false,
  });

  const status = order.data?.status;

  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: authReady && status === "delivered",
    queryFn: () => apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries`, guestAuth),
  });

  // Fallback rate CTA: even if the delivered modal was skipped or missed, a
  // logged-in buyer who hasn't reviewed this order can rate it from here. Guests
  // can't review, so the query only runs for a signed-in user on a delivered order.
  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: Boolean(user) && status === "delivered",
  });

  // Waiting on the guest token counts as loading too — the order query
  // stays disabled (and so `order.isLoading` false) until it resolves.
  if (order.isLoading || (isGuest && guestToken.isPending)) {
    return <p className="text-tx-mute">{t("loading")}</p>;
  }
  if (guestToken.isError || order.isError || !order.data) {
    return <p className="text-[#FF6B6B]">{t("notFound")}</p>;
  }

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
