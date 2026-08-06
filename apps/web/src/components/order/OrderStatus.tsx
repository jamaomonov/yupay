"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { KeyRound, MessageCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { ArtifactReceipt } from "./ArtifactReceipt";
import { GuestReviewPanel } from "./GuestReviewPanel";
import { OrderIdChip } from "./OrderIdChip";
import { OrderItems } from "./OrderItems";
import { OrderLoadError } from "./OrderLoadError";
import { isTrackedStatus, OrderProgress } from "./OrderProgress";
import { OrderStatusSkeleton } from "./OrderStatusSkeleton";
import { OrderSummary } from "./OrderSummary";
import { StatusBlock } from "./StatusBlock";

import type { OrderOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { mintGuestToken, requestCodeAccess } from "@/lib/guest";
import { getMyReviews } from "@/lib/reviews";
import { pathFor } from "@/lib/seo";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

/** Statuses that mean the order is still moving — keep polling. */
const IN_MOTION = new Set(["pending_payment", "paid", "fulfilling", "fulfilled"]);

/**
 * Statuses where a buyer may need a human: money has left the card and the
 * goods have not arrived, or the order failed outright. A delivered order does
 * not need the prompt — it has its codes.
 */
const SUPPORT_STATUSES = new Set(["pending_payment", "paid", "fulfilling", "failed"]);

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

  // Delivered codes are gated behind an order-scoped magic-link token (?access=)
  // carried by the delivered email — the freely-mintable email token above only
  // unlocks order status, never the codes. Logged-in owners use their Bearer.
  const access = useSearchParams().get("access");
  const deliveryAuth =
    isGuest && access && normalizedEmail
      ? {
          anonymous: true as const,
          headers: {
            Authorization: `Guest ${access}`,
            "X-Guest-Email": normalizedEmail,
          },
        }
      : undefined;
  // A guest can load codes only with a valid access link; a logged-in user always can.
  const canLoadCodes = !isGuest || Boolean(deliveryAuth);

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
    enabled: authReady && status === "delivered" && canLoadCodes,
    queryFn: () => apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries`, deliveryAuth),
  });

  // Guest on a delivered order without a valid access link: offer to re-mail it.
  const resend = useMutation({
    mutationFn: () => {
      if (!normalizedEmail) throw new Error("missing email");
      return requestCodeAccess(orderId, normalizedEmail);
    },
  });
  const needsAccessLink = isGuest && status === "delivered" && !deliveryAuth;

  // The order page live-updates (WS + polling), so a guest can be sitting on it
  // the moment fulfilment completes. Bring the "get your codes" action into
  // view once — without this the block appears below the fold and the customer
  // just sees "Delivered" with no codes and no obvious next step.
  const accessBlockRef = useRef<HTMLDivElement | null>(null);
  const scrolledToAccess = useRef(false);
  useEffect(() => {
    if (!needsAccessLink || scrolledToAccess.current) return;
    scrolledToAccess.current = true;
    accessBlockRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [needsAccessLink]);

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
    return <OrderStatusSkeleton />;
  }
  if (guestToken.isError || order.isError || !order.data) {
    return (
      <OrderLoadError
        locale={locale}
        onRetry={() => {
          // Re-mint the guest token too: an expired/rejected one is a common
          // cause here, and refetching only the order would fail the same way.
          void guestToken.refetch();
          void order.refetch();
        }}
      />
    );
  }

  const brandSlug = order.data.items[0]?.display?.brand_slug ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === order.data.id);
  const canRate = status === "delivered" && Boolean(user) && brandSlug !== null && !alreadyReviewed;
  // Top-up only when every item is a top-up (mirrors the Mini App's
  // `orderKind`); a mixed cart falls back to the neutral "delivered" wording.
  const isTopUp =
    order.data.items.length > 0 &&
    order.data.items.every((i) => i.display?.product_kind === "top_up");

  return (
    <div className="space-y-4">
      {/* Back to the order list — /account/orders renders the logged-in history
          AND (for guests) this browser's local order history, so it's the right
          target for everyone. Lets a guest who navigated away return to it. */}
      <Link
        href={pathFor(locale, "/account/orders")}
        className="text-tx-mute hover:text-foreground inline-flex items-center gap-1.5 text-sm transition"
      >
        <span aria-hidden>←</span> {t("backToOrders")}
      </Link>
      <div className="border-border bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
        <div className="space-y-3">
          <OrderIdChip orderId={order.data.id} />
          <StatusBlock status={order.data.status} isTopUp={isTopUp} />
          {/* Timeline only for the happy path — see OrderProgress on why a
              refunded/failed order gets the status hero alone. */}
          {isTrackedStatus(order.data.status) && (
            <div className="border-border/70 border-t pt-4">
              <OrderProgress status={order.data.status} isTopUp={isTopUp} />
            </div>
          )}
        </div>

        <OrderSummary order={order.data} />

        <OrderItems items={order.data.items} />

        {status === "delivered" &&
          canLoadCodes &&
          deliveries.data?.items.map((d) => <ArtifactReceipt key={d.id} artifact={d.artifact} />)}

        {needsAccessLink && (
          <div
            ref={accessBlockRef}
            // Accented (not the neutral card tone): this is the one action left
            // between the customer and the goods they paid for, and it used to
            // read as a footnote under the item list.
            className="border-primary/35 bg-primary/[0.06] space-y-3 rounded-xl border p-4"
          >
            <div className="flex items-start gap-2.5">
              <KeyRound size={18} className="text-primary mt-0.5 shrink-0" aria-hidden="true" />
              <div className="min-w-0 space-y-1">
                <p className="text-foreground text-sm font-semibold">{t("codesReadyTitle")}</p>
                <p className="text-tx-mute text-sm leading-snug">{t("codesNeedAccess")}</p>
              </div>
            </div>
            {resend.isSuccess ? (
              <p className="text-sm text-[#3D7A00]">{t("accessLinkSent")}</p>
            ) : (
              <button
                type="button"
                onClick={() => {
                  resend.mutate();
                }}
                disabled={resend.isPending}
                className={buttonStyles({ size: "sm" })}
              >
                {resend.isPending ? t("loading") : t("sendAccessLink")}
              </button>
            )}
            {/* A send failure is not a missing order — say what actually went wrong. */}
            {resend.isError && <p className="text-sm text-[#FF6B6B]">{t("accessLinkFailed")}</p>}
          </div>
        )}

        {/* Support, where the worry actually happens. The floating help pill is
            desktop-only on purpose (it would collide with the mobile pay bar),
            and this page had no support link at all — while its own copy said
            "поддержка на связи" and "обратитесь в поддержку", which were words
            rather than anything tappable. The order number rides the deep link
            so the first message already carries it. */}
        {status && SUPPORT_STATUSES.has(status) && (
          <a
            href={`https://t.me/yupay_support?text=${encodeURIComponent(`Заказ #${order.data.id.slice(0, 8)}`)}`}
            target="_blank"
            rel="noreferrer noopener"
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            <MessageCircle size={15} strokeWidth={2.2} aria-hidden />
            {t("supportCta")}
          </a>
        )}

        {canRate && brandSlug && (
          <Link
            href={pathFor(locale, `/store/${brandSlug}?order=${order.data.id}#reviews`)}
            className={buttonStyles({ size: "sm" })}
          >
            {tr("writeCta")}
          </Link>
        )}

        {status === "delivered" && !user && email && brandSlug && (
          <GuestReviewPanel orderId={order.data.id} email={email} />
        )}
      </div>
    </div>
  );
}
