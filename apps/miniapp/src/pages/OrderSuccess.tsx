/**
 * Order success / status page.
 *
 * Mounted at ``/order/:id``. Drives the post-checkout journey:
 *
 *   pending_payment ─► paid ─► fulfilling ─► delivered  → show codes
 *                                       └─► cancelled / expired → show error
 *
 * Polls ``useOrder`` while the order is in motion and surfaces delivery
 * artifacts (voucher codes, receipts, license keys) the moment they appear.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CreditCard, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams, Link } from "wouter";

import type { DeliveryOut } from "@/lib/orders";

import { ActionButton } from "@/components/order/ActionButton";
import { DeliveredExtras } from "@/components/order/DeliveredExtras";
import { ErrorView } from "@/components/order/ErrorView";
import { ItemCard } from "@/components/order/ItemCard";
import { AWAITING_DELIVERY, PROCESSING, TERMINAL_FAIL } from "@/components/order/order-helpers";
import { SkeletonView } from "@/components/order/SkeletonView";
import { StatusCard, stageFor } from "@/components/order/StatusCard";
import { Summary } from "@/components/order/Summary";
import { WalletFundingStatus } from "@/components/order/WalletFundingStatus";
import { RateAsk } from "@/components/review/RateAsk";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useActivePayment, useDeliveries, useOrder } from "@/lib/orders";
import { getMyReviews } from "@/lib/reviews";
import { hrefForGameSlug } from "@/lib/routes";
import { openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

// Re-exported so existing test imports (`./OrderSuccess`) keep working after
// these pure helpers moved to `components/order/order-helpers.ts`.
export {
  isGiftDelivery,
  pickArtifactDisplay,
  providerIcon,
  providerLabel,
} from "@/components/order/order-helpers";

function useElapsedSeconds(start: string | null | undefined, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    // 5s tick is enough — thresholds are minute-grained, sub-second precision
    // is wasted CPU and battery.
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 5_000);
    return () => {
      window.clearInterval(id);
    };
  }, [active]);
  if (!start) return 0;
  const startedAt = new Date(start).getTime();
  if (!Number.isFinite(startedAt)) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

export default function OrderSuccess() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const orderId = params.id;
  const [, setLocation] = useLocation();
  useDocumentTitle(
    orderId ? t("success.docTitleNamed", { id: orderId.slice(0, 8) }) : t("success.docTitle"),
  );

  const qc = useQueryClient();
  const orderQuery = useOrder(orderId);
  const order = orderQuery.data;

  // An admin refund credits the customer's wallet back (for wallet-funded
  // orders). When the status poll observes the order land in ``refunded``,
  // refresh the wallet queries so the header balance reflects the credit
  // without a manual reload. Keyed on the status so it fires once on the
  // transition (and harmlessly once if the page opens already-refunded).
  useEffect(() => {
    if (order?.status === "refunded") {
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    }
  }, [order?.status, qc]);

  // Guard the window that actually matters. Checkout turns the confirmation on
  // for the few hundred milliseconds of its own request and back off in
  // `finally` — correctly, because that path navigates to the acquirer rather
  // than closing. The risk starts afterwards: the buyer is back in Telegram
  // with the order still unpaid, the payment possibly in flight, and one stray
  // swipe-down closes the app.
  useEffect(() => {
    if (order?.status !== "pending_payment") return;
    setClosingConfirmation(true);
    return () => {
      setClosingConfirmation(false);
    };
  }, [order?.status]);

  const deliveriesQuery = useDeliveries(orderId, order?.status);
  const deliveries = deliveriesQuery.data ?? [];

  // Fallback rate CTA: if the delivered dialog was skipped or missed, a
  // signed-in buyer who hasn't reviewed this order can still rate it here.
  const me = useMe();
  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: Boolean(me.data) && order?.status === "delivered",
  });

  // Lookup the in-flight payment intent for a still-unpaid order so we can
  // surface a «Оплатить» button that jumps straight to the acquirer's hosted
  // page. The hook gates itself on ``status === "pending_payment"`` and 404s
  // gracefully once the order walks forward.
  const paymentQuery = useActivePayment(orderId, order?.status);
  const payUrl = paymentQuery.data?.intent_url ?? null;

  // Map delivered artifacts back to their items so we can render brand + denom
  // alongside each artifact block.
  const deliveriesByItem = useMemo(() => {
    const map: Record<string, DeliveryOut> = {};
    for (const d of deliveries) map[d.order_item_id] = d;
    return map;
  }, [deliveries]);

  // Elapsed since the *payment* was confirmed (or since creation when the
  // order is still ``pending_payment``). Drives the soft-SLA copy on the
  // status card — "ждём 5 минут" must mean five minutes of *fulfilment*,
  // not "the customer opened checkout five minutes ago and only just paid".
  // Ticking pauses once the order reaches a terminal state.
  // IMPORTANT: this hook MUST be called before any early return — otherwise
  // we run a different number of hooks on first render (loading) vs second
  // (data), which is the classic "Rendered more hooks than during the
  // previous render" violation.
  const isProcessingOrUnknown = order ? PROCESSING.includes(order.status) : false;
  const elapsed = useElapsedSeconds(order?.paid_at ?? order?.created_at, isProcessingOrUnknown);

  if (!orderId) {
    return (
      <ErrorView
        title={t("success.notFoundTitle")}
        subtitle={t("success.notFoundSubtitle")}
        onHome={() => {
          setLocation("/");
        }}
      />
    );
  }

  if (orderQuery.isLoading || !order) {
    return (
      <SkeletonView
        onBack={() => {
          setLocation("/");
        }}
      />
    );
  }

  if (order.purpose === "wallet_topup") {
    return (
      <WalletFundingStatus
        order={order}
        payUrl={payUrl}
        onWallet={() => {
          setLocation("/wallet");
        }}
        onHome={() => {
          setLocation("/");
        }}
      />
    );
  }

  const stage = stageFor(order);
  const isProcessing = isProcessingOrUnknown;
  const isDelivered = order.status === "delivered";
  const rateBrandSlug = order.items[0]?.display?.brand_slug ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === order.id);
  const canRate = isDelivered && Boolean(me.data) && rateBrandSlug !== null && !alreadyReviewed;
  const isFailed = TERMINAL_FAIL.includes(order.status);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="space-y-4 pb-6"
    >
      <header className="flex items-center gap-3 px-4 pt-3">
        {/* Telegram's BackButton covers this route and returns where the
            buyer came from; this one always went to History, even for someone
            who had just arrived from checkout. */}
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.08em] text-white/35">
            {t("success.orderLabel")}
          </p>
          <p className="truncate font-mono text-sm leading-tight text-white">
            {order.id.slice(0, 8)}…
          </p>
        </div>
      </header>

      <StatusCard
        order={order}
        stage={stage}
        isProcessing={isProcessing}
        isDelivered={isDelivered}
        isFailed={isFailed}
        elapsedSeconds={elapsed}
      />

      {/* Per-item delivery artifacts. The "awaiting" placeholder is gated
          on actual fulfilment activity (see AWAITING_DELIVERY) — for
          unpaid / expired / cancelled orders we render just the item line. */}
      <section className="space-y-2 px-4">
        {order.items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            delivery={deliveriesByItem[item.id] ?? null}
            currency={order.currency}
            awaitingDelivery={AWAITING_DELIVERY.includes(order.status)}
          />
        ))}
      </section>

      <Summary order={order} />

      <div
        className={`px-4 pt-2 ${
          order.status === "pending_payment" && payUrl ? "grid grid-cols-2 gap-3" : ""
        }`}
      >
        {order.status === "pending_payment" && payUrl && (
          <ActionButton
            icon={<CreditCard size={15} />}
            label={t("success.payNow")}
            variant="primary"
            // Opens in the device browser (or Telegram's in-app overlay), not
            // in place of the mini app — keeping the app and its back arrow
            // intact. See ``openExternalLink``.
            onClick={() => {
              openExternalLink(payUrl);
            }}
          />
        )}
        <Link
          href={
            order.items[0]?.display?.brand_slug
              ? hrefForGameSlug(order.items[0].display.brand_slug)
              : "/"
          }
        >
          <ActionButton
            icon={<Sparkles size={15} />}
            label={t("success.buyMore")}
            variant={order.status === "pending_payment" && payUrl ? "secondary" : "primary"}
          />
        </Link>
      </div>

      {isDelivered && canRate && rateBrandSlug && (
        <div className="px-4">
          <RateAsk
            orderId={order.id}
            brandSlug={rateBrandSlug}
            brandName={order.items[0]?.display?.brand_name ?? null}
          />
        </div>
      )}

      {isDelivered && (
        <DeliveredExtras
          brandName={order.items[0]?.display?.brand_name ?? null}
          imageUrl={order.items[0]?.display?.image_url ?? null}
        />
      )}
    </motion.div>
  );
}

// Auto-scroll to top when the page is opened by a router change. The wouter
// router preserves scroll between routes by default, which makes the success
// page feel "stale" if the user was scrolled deep on TopUp.
export function useScrollToTopOnMount(): void {
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, []);
}
