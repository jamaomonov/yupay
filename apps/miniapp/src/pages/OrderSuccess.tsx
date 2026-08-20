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
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  CreditCard,
  ExternalLink,
  HeadphonesIcon,
  Home,
  Loader2,
  Share2,
  ShoppingBag,
  Sparkles,
  Star,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams, Link } from "wouter";

import { ReviewsSheet } from "@/components/ReviewsSheet";
import { SafeImage } from "@/components/ui/safe-image";
import { useToast } from "@/hooks/use-toast";
import { useMe } from "@/lib/auth";
import { useT, type MessageKey } from "@/lib/i18n";
import { getActiveLocale, translate } from "@/lib/i18n/core";
import {
  useActivePayment,
  useDeliveries,
  useOrder,
  type ArtifactKind,
  type DeliveryOut,
  type OrderOut,
  type OrderStatus,
  type ProductKind,
} from "@/lib/orders";
import { ICON_BY_PROVIDER } from "@/lib/payment-methods";
import { getMyReviews } from "@/lib/reviews";
import {
  addToHomeScreen,
  canShareToStory,
  getHomeScreenStatus,
  openExternalLink,
  setClosingConfirmation,
  shareToStory,
} from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

const PROCESSING: OrderStatus[] = ["pending_payment", "paid", "fulfilling", "fulfilled"];

const TERMINAL_FAIL: OrderStatus[] = ["cancelled", "expired", "refunded"];

// Subset of PROCESSING where a delivery is actually being attempted. We hide
// "ожидаем выдачу…" / "пополняем аккаунт…" placeholders outside of these
// states — pending_payment hasn't been paid yet, and expired/cancelled/
// refunded will never fulfil. Showing the spinner there was misleading.
const AWAITING_DELIVERY: OrderStatus[] = ["paid", "fulfilling", "fulfilled"];

// Soft SLA thresholds. The order is allowed to take whatever it takes
// (fulfillment can poll suppliers, manual intervention etc.), but we lower
// the user's anxiety after a couple of minutes by surfacing a support escape.
const SLA_WARN_SECONDS = 3 * 60; // show "long? support" link
const SLA_DELAYED_SECONDS = 10 * 60; // upgrade subtitle to "задерживается"

const SUPPORT_USERNAME = (
  (import.meta.env.VITE_TELEGRAM_SUPPORT_USERNAME as string | undefined) ??
  (import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined) ??
  ""
).replace(/^@/, "");

function supportDeepLink(orderId: string): string | null {
  if (!SUPPORT_USERNAME) return null;
  // Telegram's t.me deep-link with a prefilled message body — when the user
  // taps "Поддержка" Telegram pops the chat with this text in the composer.
  const text = encodeURIComponent(translate("success.supportMessage", { orderId }));
  return `https://t.me/${SUPPORT_USERNAME}?text=${text}`;
}

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

function formatElapsed(seconds: number): string {
  if (seconds < 60) return translate("success.elapsedSec", { n: seconds });
  const minutes = Math.floor(seconds / 60);
  return translate("success.elapsedMin", { n: minutes });
}

interface StageCopy {
  title: string;
  subtitle: string;
}

/** What's this order made of? Drives status copy so a top-up never
 *  promises a "code" and a voucher never says "credited to account".
 *  ``mixed`` (both kinds in one order) falls back to neutral wording. */
function orderKind(order: OrderOut): "top_up" | "voucher" | "mixed" {
  const kinds = new Set(
    order.items.map((i) => i.display?.product_kind).filter((k): k is ProductKind => Boolean(k)),
  );
  if (kinds.size === 1) {
    return kinds.has("top_up") ? "top_up" : "voucher";
  }
  return "mixed";
}

function stageFor(order: OrderOut): StageCopy {
  const kind = orderKind(order);
  switch (order.status) {
    case "pending_payment":
      return {
        title: translate("success.stage.pendingTitle"),
        subtitle: translate("success.stage.pendingSub"),
      };
    case "paid":
      return {
        title: translate("success.stage.paidTitle"),
        subtitle: translate("success.stage.paidSub"),
      };
    case "fulfilling":
      return {
        title: translate("success.stage.fulfillingTitle"),
        subtitle:
          kind === "top_up"
            ? translate("success.stage.fulfillingSubTopUp")
            : kind === "voucher"
              ? translate("success.stage.fulfillingSubVoucher")
              : translate("success.stage.fulfillingSubMixed"),
      };
    case "fulfilled":
      return {
        title: translate("success.stage.fulfilledTitle"),
        subtitle: translate("success.stage.fulfilledSub"),
      };
    case "delivered":
      return {
        title: translate("success.stage.deliveredTitle"),
        subtitle:
          kind === "top_up"
            ? translate("success.stage.deliveredSubTopUp")
            : translate("success.stage.deliveredSubOther"),
      };
    case "cancelled":
      return {
        title: translate("success.stage.cancelledTitle"),
        subtitle: translate("success.stage.cancelledSub"),
      };
    case "expired":
      return {
        title: translate("success.stage.expiredTitle"),
        subtitle: translate("success.stage.expiredSub"),
      };
    case "refunded":
      return {
        title: translate("success.stage.refundedTitle"),
        subtitle: translate("success.stage.refundedSub"),
      };
  }
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
  const [reviewOpen, setReviewOpen] = useState(false);

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
              ? `/topup/${order.items[0].display.brand_slug}`
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

      {isDelivered && (
        <DeliveredExtras
          brandName={order.items[0]?.display?.brand_name ?? null}
          imageUrl={order.items[0]?.display?.image_url ?? null}
          canRate={canRate}
          onRate={() => {
            setReviewOpen(true);
          }}
        />
      )}

      {reviewOpen && rateBrandSlug && (
        <ReviewsSheet
          brandSlug={rateBrandSlug}
          formOrderId={order.id}
          onClose={() => {
            setReviewOpen(false);
          }}
        />
      )}
    </motion.div>
  );
}

/**
 * Post-delivery offers: pin the app, brag about the top-up.
 *
 * Deliberately only on a delivered order — asking someone to install a
 * shortcut before they know the purchase worked is noise. Each affordance
 * hides itself unless the client actually supports it, so on older Telegram
 * versions this section simply isn't there.
 */
function DeliveredExtras({
  brandName,
  imageUrl,
  canRate,
  onRate,
}: {
  brandName: string | null;
  imageUrl: string | null;
  canRate: boolean;
  onRate: () => void;
}) {
  const { t } = useT();
  const [canPin, setCanPin] = useState(false);
  const canShare = canShareToStory() && Boolean(imageUrl);

  useEffect(() => {
    let alive = true;
    void getHomeScreenStatus().then((status) => {
      // "missed" = supported and not installed yet. "added" / "unsupported" /
      // null all mean there's nothing worth offering.
      if (alive) setCanPin(status === "missed");
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!canPin && !canShare && !canRate) return null;

  return (
    <div className="grid grid-cols-2 gap-3 px-4 pt-1">
      {canPin && (
        <ActionButton
          icon={<Home size={15} />}
          label={t("success.addToHome")}
          variant="secondary"
          onClick={() => {
            addToHomeScreen();
          }}
        />
      )}
      {canShare && imageUrl && (
        <ActionButton
          icon={<Share2 size={15} />}
          label={t("success.share")}
          variant="secondary"
          onClick={() => {
            shareToStory(imageUrl, {
              text: brandName
                ? t("success.shareStoryText", { game: brandName })
                : t("success.shareStoryTextGeneric"),
            });
          }}
        />
      )}
      {canRate && (
        <ActionButton
          icon={<Star size={15} />}
          label={t("reviews.rateCta")}
          variant="secondary"
          onClick={onRate}
        />
      )}
    </div>
  );
}

// ─── Status card ─────────────────────────────────────────────────────────────

function StatusCard({
  order,
  stage,
  isProcessing,
  isDelivered,
  isFailed,
  elapsedSeconds,
}: {
  order: OrderOut;
  stage: StageCopy;
  isProcessing: boolean;
  isDelivered: boolean;
  isFailed: boolean;
  elapsedSeconds: number;
}) {
  const { t } = useT();
  const tone = isDelivered
    ? "delivered"
    : isFailed
      ? "failed"
      : isProcessing
        ? "processing"
        : "neutral";

  const accent =
    tone === "delivered"
      ? "hsl(var(--primary))"
      : tone === "failed"
        ? "#ef4444"
        : "hsl(220 70% 60%)";

  const isDelayed = isProcessing && elapsedSeconds >= SLA_DELAYED_SECONDS;
  // Slow order → soft escape after the SLA warning; terminal failure
  // (cancelled / expired / refunded) → support immediately, that's exactly
  // the moment the customer wants a human.
  const showSupport = isFailed || (isProcessing && elapsedSeconds >= SLA_WARN_SECONDS);
  const subtitle = isDelayed ? t("success.delayedSub") : stage.subtitle;

  const supportHref = supportDeepLink(order.id);

  return (
    <div className="px-4">
      <div
        className="relative overflow-hidden rounded-3xl p-5"
        style={{
          background: "hsl(var(--surface-1))",
          border: `1px solid ${tone === "delivered" ? "hsl(var(--primary) / 0.4)" : "hsl(var(--border))"}`,
        }}
      >
        {/* Glow */}
        <div
          className="pointer-events-none absolute -right-12 -top-12 size-44 rounded-full opacity-30 blur-3xl"
          style={{ background: accent }}
        />

        {/* Wrapping the status copy in an aria-live region lets screen
            readers announce stage transitions (paid → fulfilling → delivered)
            without yanking focus. `polite` so it queues behind whatever the
            user is doing; `assertive` would interrupt mid-typing. */}
        <div
          className="relative flex items-center gap-3"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <StatusIcon tone={tone} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <h1 className="text-lg font-bold leading-tight text-white">{stage.title}</h1>
              {isProcessing && elapsedSeconds > 0 && (
                <span className="text-[11px] font-medium tabular-nums text-white/35">
                  · {formatElapsed(elapsedSeconds)}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs leading-snug text-white/55">{subtitle}</p>
          </div>
        </div>

        {/* Progress strip — only while in motion. */}
        {isProcessing && (
          <div
            className="relative mt-4 h-1 overflow-hidden rounded-full bg-white/5"
            role="progressbar"
            aria-valuetext={t("success.processingAria")}
            aria-busy="true"
          >
            <motion.div
              className="absolute inset-y-0 left-0 w-1/3 rounded-full"
              style={{ background: accent }}
              animate={{ x: ["-100%", "300%"] }}
              transition={{
                duration: 1.6,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
          </div>
        )}

        {/* Soft SLA escape: after a couple of minutes show a low-stress link
            to support. We don't expose a cancel/refund button here — refunds
            are mediated by support to keep the rules consistent across
            providers. */}
        {showSupport && supportHref && (
          <motion.a
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            href={supportHref}
            className="relative mt-4 flex items-center justify-between gap-2 rounded-2xl px-3 py-2.5 transition-opacity active:opacity-70"
            style={{
              background: "hsl(var(--surface-2))",
              border: "1px solid hsl(var(--border))",
            }}
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <div
                className="flex size-7 flex-shrink-0 items-center justify-center rounded-lg"
                style={{
                  background: "hsl(var(--primary) / 0.15)",
                  color: "hsl(var(--primary))",
                }}
                aria-hidden="true"
              >
                <HeadphonesIcon size={13} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold leading-tight text-white">
                  {isDelayed ? t("success.supportWrite") : t("success.supportLong")}
                </p>
                <p className="mt-0.5 truncate text-[10px] leading-tight text-white/40">
                  {t("success.supportHint")}
                </p>
              </div>
            </div>
            <ExternalLink size={13} className="flex-shrink-0 text-white/40" />
          </motion.a>
        )}
      </div>
    </div>
  );
}

function StatusIcon({ tone }: { tone: "delivered" | "failed" | "processing" | "neutral" }) {
  if (tone === "delivered") {
    return (
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 280, damping: 18 }}
        className="flex size-11 flex-shrink-0 items-center justify-center rounded-2xl"
        style={{
          background: "linear-gradient(140deg, hsl(var(--primary)) 0%, hsl(84 100% 70%) 100%)",
          boxShadow: "0 8px 24px hsl(var(--primary) / 0.4)",
        }}
      >
        <CheckCircle2 size={22} strokeWidth={2.5} className="text-black" />
      </motion.div>
    );
  }
  if (tone === "failed") {
    return (
      <div
        className="flex size-11 flex-shrink-0 items-center justify-center rounded-2xl"
        style={{ background: "rgba(239, 68, 68, 0.18)" }}
      >
        <XCircle size={22} className="text-red-400" />
      </div>
    );
  }
  return (
    <div
      className="flex size-11 flex-shrink-0 items-center justify-center rounded-2xl"
      style={{ background: "rgba(255, 255, 255, 0.05)" }}
    >
      <Loader2 size={20} className="animate-spin text-white/70" />
    </div>
  );
}

// ─── Per-item card ───────────────────────────────────────────────────────────

function ItemCard({
  item,
  delivery,
  currency,
  awaitingDelivery,
}: {
  item: OrderOut["items"][number];
  delivery: DeliveryOut | null;
  currency: string;
  awaitingDelivery: boolean;
}) {
  const { t } = useT();
  const display = item.display;
  const headline = display
    ? display.brand_name
      ? `${display.brand_name} · ${display.denomination ?? display.sku_code}`
      : `${display.product_name || display.product_slug} · ${display.denomination ?? display.sku_code}`
    : `SKU ${item.sku_id.slice(0, 8)}…`;

  const isTopUp = display?.product_kind === "top_up";

  return (
    <div
      className="rounded-2xl p-3.5"
      style={{
        background: "hsl(var(--surface-1))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <div className="flex items-center gap-3">
        {display?.image_url ? (
          <SafeImage
            src={display.image_url}
            className="size-11 flex-shrink-0 rounded-xl object-cover"
            fallback={
              <div
                className="flex size-11 flex-shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white/40"
                style={{ background: "hsl(var(--surface-2))" }}
              >
                {display?.brand_name?.[0]?.toUpperCase() ?? "?"}
              </div>
            }
          />
        ) : (
          <div
            className="flex size-11 flex-shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white/40"
            style={{ background: "hsl(var(--surface-2))" }}
          >
            {display?.brand_name?.[0]?.toUpperCase() ?? "?"}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-tight text-white">{headline}</p>
          {/* Never surface the USD unit price to the customer — the charge is in
              their own currency (shown in the order-summary "Сумма" row). */}
          {item.qty > 1 && (
            <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/40">
              <span>×{item.qty}</span>
            </p>
          )}
        </div>
      </div>

      <AnimatePresence>
        {delivery ? (
          isTopUp ? (
            <TopUpReceipt
              delivery={delivery}
              fulfillmentData={item.fulfillment_data}
              // A variable-amount SKU's own `denomination` is a generic
              // "Любая сумма" label — `unit_price_usd` on this item IS the
              // dollar amount the customer chose to credit (see
              // `OrderItemDisplay.variable_amount` on the API), and is the
              // only place that amount is ever shown to them.
              creditedUsd={display?.variable_amount ? item.unit_price_usd : null}
            />
          ) : (
            <ArtifactBlock delivery={delivery} />
          )
        ) : awaitingDelivery ? (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 flex items-center gap-2 text-[11px] text-white/40"
          >
            <Loader2 size={12} className="animate-spin" />
            <span>{isTopUp ? t("success.awaitingTopUp") : t("success.awaitingVoucher")}</span>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

// ─── Top-up receipt ─────────────────────────────────────────────────────────
// For top-up products there is no code to deliver — the supplier credits the
// player's account directly. The receipt block surfaces:
//   * the fields the user entered at checkout (player_id, region, …) so they
//     can confirm we pushed UC to the right account;
//   * the supplier's order id, in case support needs it later.

const FIELD_LABEL: Record<string, MessageKey> = {
  player_id: "success.field.player_id",
  user_id: "success.field.user_id",
  account_id: "success.field.account_id",
  email: "success.field.email",
  phone: "success.field.phone",
  region: "success.field.region",
  zone_id: "success.field.zone_id",
  character: "success.field.character",
  nickname: "success.field.nickname",
};

function labelForField(key: string): string {
  const messageKey = FIELD_LABEL[key];
  return messageKey ? translate(messageKey) : key;
}

function TopUpReceipt({
  delivery,
  fulfillmentData,
  creditedUsd,
}: {
  delivery: DeliveryOut;
  fulfillmentData: Record<string, unknown>;
  /** The dollar amount credited, for a variable-amount SKU (Steam wallet).
   *  `null` for a fixed-denomination top-up — its package name already says
   *  what was bought, so repeating the USD unit price would just be noise. */
  creditedUsd: string | null;
}) {
  const { t } = useT();
  // Prefer the snapshot stored in the artifact (frozen at fulfilment time),
  // fall back to the live item.fulfillment_data if the supplier didn't echo
  // it back.
  const artifactSnapshot = isStringRecord(delivery.artifact.fulfillment_data)
    ? delivery.artifact.fulfillment_data
    : null;
  const fields = artifactSnapshot ?? fulfillmentData;

  const entries = Object.entries(fields).filter(
    ([, v]) => typeof v === "string" && v.trim().length > 0,
  ) as [string, string][];

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-3 space-y-2"
    >
      <div className="flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {t("success.credited")}
        </span>
        <span className="text-[10px] text-white/25">·</span>
        <span className="text-[10px] text-white/35">
          {new Date(delivery.delivered_at).toLocaleString(getActiveLocale(), {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {(creditedUsd !== null || entries.length > 0) && (
        <div
          className="space-y-1.5 rounded-xl p-3"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {creditedUsd !== null && (
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{t("success.creditedAmount")}</span>
              <span className="text-right font-mono font-semibold text-white">
                ${Number.parseFloat(creditedUsd).toFixed(2)}
              </span>
            </div>
          )}
          {entries.map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{labelForField(key)}</span>
              <span className="max-w-[60%] truncate text-right font-mono text-white">{value}</span>
            </div>
          ))}
        </div>
      )}
      {/* The supplier's external_id is stored in the artifact for support
          / chargeback evidence, but isn't useful to the customer — and
          surfacing it invited "что значит этот номер?" support tickets.
          Admins still see it via /admin/fulfillment task details. */}
    </motion.div>
  );
}

function isStringRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ─── Artifact block ──────────────────────────────────────────────────────────

/** Ordered preference for the artifact's primary copyable identifier — the
 *  first non-empty string value wins. Every key here is part of the API's
 *  customer-facing whitelist (`_CUSTOMER_SAFE_ARTIFACT_KEYS` in
 *  `fulfillment/routes.py`) — never read `external_id`: no supplier or
 *  admin-manual-completion flow reaching this component ever sets it, and
 *  Phase 1 strips it server-side if one did. */
const COPYABLE_ARTIFACT_KEYS = ["code", "key", "pin", "serial", "steam_login", "login"] as const;
type CopyableArtifactKey = (typeof COPYABLE_ARTIFACT_KEYS)[number];

const COPYABLE_ARTIFACT_LABEL: Record<CopyableArtifactKey, MessageKey> = {
  code: "success.code",
  key: "success.key",
  pin: "success.pin",
  serial: "success.serial",
  steam_login: "success.steamLogin",
  login: "success.login",
};

type ArtifactDisplay =
  | { kind: "copyable"; artifactKey: CopyableArtifactKey; value: string }
  | { kind: "text"; value: string }
  | { kind: "fields"; entries: [string, string][] }
  | { kind: "empty" };

/**
 * Decide how to render a non-top-up delivery artifact: a copyable
 * identifier first (code/key/pin/serial/steam_login/login), then a
 * free-text delivery note (message/note — e.g. an admin-manual-completion
 * that hands over an account without a single code/key field), then the
 * customer's own `fulfillment_data` snapshot, and only a bare "credited"
 * line if none of the whitelisted keys carry anything to show. Exported for
 * unit testing — pure, no i18n/React dependency.
 */
export function pickArtifactDisplay(artifact: Record<string, unknown>): ArtifactDisplay {
  for (const key of COPYABLE_ARTIFACT_KEYS) {
    const value = artifact[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return { kind: "copyable", artifactKey: key, value };
    }
  }
  for (const key of ["message", "note"] as const) {
    const value = artifact[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return { kind: "text", value };
    }
  }
  if (isStringRecord(artifact.fulfillment_data)) {
    const entries = Object.entries(artifact.fulfillment_data).filter(
      (entry): entry is [string, string] =>
        typeof entry[1] === "string" && entry[1].trim().length > 0,
    );
    if (entries.length > 0) return { kind: "fields", entries };
  }
  return { kind: "empty" };
}

function ArtifactBlock({ delivery }: { delivery: DeliveryOut }) {
  const { toast } = useToast();
  const { t } = useT();

  const onCopy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast({ title: t("success.copied", { label }) });
    } catch {
      toast({
        title: t("common.copyFailed"),
        description: t("common.copyManual"),
        variant: "destructive",
      });
    }
  };

  const display = pickArtifactDisplay(delivery.artifact);

  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {labelForKind(delivery.artifact_kind)}
        </span>
        <span className="text-[10px] text-white/25">·</span>
        <span className="text-[10px] text-white/35">
          {new Date(delivery.delivered_at).toLocaleString(getActiveLocale(), {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {display.kind === "copyable" && (
        <CopyableValue
          value={display.value}
          label={t(COPYABLE_ARTIFACT_LABEL[display.artifactKey])}
          onCopy={(v) => void onCopy(v, t(COPYABLE_ARTIFACT_LABEL[display.artifactKey]))}
        />
      )}
      {display.kind === "text" && (
        <div
          className="rounded-xl px-3 py-2.5 text-xs leading-snug text-white/75"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <span className="text-white/45">{t("success.credited")} · </span>
          <span>{display.value}</span>
        </div>
      )}
      {display.kind === "fields" && (
        <div
          className="space-y-1.5 rounded-xl p-3"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {display.entries.map(([field, value]) => (
            <div key={field} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{labelForField(field)}</span>
              <span className="max-w-[60%] truncate text-right font-mono text-white">{value}</span>
            </div>
          ))}
        </div>
      )}
      {display.kind === "empty" && (
        <div
          className="rounded-xl px-3 py-2.5 text-xs leading-snug text-white/60"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {t("success.credited")}
        </div>
      )}
    </motion.div>
  );
}

function labelForKind(kind: ArtifactKind): string {
  switch (kind) {
    case "voucher_code":
      return translate("success.kind.voucher");
    case "license_key":
      return translate("success.kind.license");
    case "topup_receipt":
      return translate("success.kind.receipt");
  }
}

function CopyableValue({
  value,
  label,
  onCopy,
}: {
  value: string;
  label: string;
  onCopy: (v: string) => void;
}) {
  return (
    <button
      onClick={() => {
        onCopy(value);
      }}
      className="group flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors active:scale-[0.99]"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1.5px solid hsl(var(--primary) / 0.45)",
      }}
    >
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-wide text-white/40">{label}</p>
        <p className="mt-0.5 break-all font-mono text-sm text-white">{value}</p>
      </div>
      <div
        className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors"
        style={{ background: "hsl(var(--primary) / 0.18)" }}
      >
        <Copy size={13} style={{ color: "hsl(var(--primary))" }} />
      </div>
    </button>
  );
}

/**
 * Map a payment-provider slug to the label shown on the order summary.
 * Mirrors ``paymentProviderDisplay`` on web
 * (apps/web/src/lib/payment-providers.ts). Backend already normalizes
 * ``click_miniapp`` → ``click``; we tolerate both. Returns null when there is
 * no provider yet (unpaid order).
 */
export function providerLabel(provider: string | null): string | null {
  switch (provider) {
    case "click":
    case "click_miniapp":
      return "Click";
    case "payme":
      return "Payme";
    case "uzum":
      return "Uzum";
    case "octo":
      return "Octo";
    case "wallet":
      return translate("success.paidWithWallet");
    case null:
    case "":
      return null;
    default:
      return provider;
  }
}

/**
 * Small brand mark for the same provider slugs ``providerLabel`` handles.
 * ``null`` for providers with no asset (wallet, Octo, unrecognised slugs) —
 * the label text is all those get.
 */
export function providerIcon(provider: string | null): string | null {
  if (!provider) return null;
  return ICON_BY_PROVIDER[provider] ?? null;
}

// ─── Summary footer ─────────────────────────────────────────────────────────

function Summary({ order }: { order: OrderOut }) {
  const { t } = useT();
  const providerText = providerLabel(order.payment_provider);
  const providerIconSrc = providerIcon(order.payment_provider);
  return (
    <div className="px-4">
      <div
        className="space-y-1.5 rounded-2xl p-4 text-xs"
        style={{
          background: "hsl(var(--surface-1))",
          border: "1px solid hsl(var(--border))",
        }}
      >
        <Row
          label={t("success.amount")}
          value={`${Number.parseFloat(order.total_charged).toLocaleString(getActiveLocale(), { maximumFractionDigits: 2 })} ${order.currency}`}
        />
        {providerText && (
          <Row label={t("success.paidWith")} value={providerText} icon={providerIconSrc} />
        )}
        <Row label={t("success.createdAt")} value={fmtDate(order.created_at)} />
        {order.paid_at && <Row label={t("success.paidAt")} value={fmtDate(order.paid_at)} />}
        {order.delivered_at && (
          <Row label={t("success.deliveredAt")} value={fmtDate(order.delivered_at)} />
        )}
      </div>
    </div>
  );
}

function Row({ label, value, icon }: { label: string; value: string; icon?: string | null }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-white/45">{label}</span>
      <span className="flex items-center gap-1.5 font-medium text-white">
        {icon && (
          <span className="flex h-4 w-4 items-center justify-center overflow-hidden rounded-sm bg-white">
            <img src={icon} alt="" className="h-full w-full object-contain" />
          </span>
        )}
        {value}
      </span>
    </div>
  );
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(getActiveLocale(), {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Action buttons ─────────────────────────────────────────────────────────

function ActionButton({
  icon,
  label,
  variant,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  variant: "primary" | "secondary";
  onClick?: () => void;
}) {
  const primary = variant === "primary";
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-2 rounded-2xl py-3 text-sm font-semibold transition-transform active:scale-[0.97]"
      style={{
        background: primary ? "hsl(var(--primary))" : "hsl(var(--surface-2))",
        color: primary ? "hsl(var(--primary-foreground))" : "rgba(255,255,255,0.85)",
        border: primary ? "1px solid hsl(var(--primary))" : "1px solid hsl(var(--border))",
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ─── Skeleton + error ───────────────────────────────────────────────────────

function SkeletonView({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-4 pb-6">
      <header className="flex items-center gap-3 px-4 pt-3">
        <button
          onClick={onBack}
          className="flex size-9 items-center justify-center rounded-xl"
          style={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <ArrowLeft size={15} className="text-white/60" />
        </button>
        <div
          className="h-3 flex-1 animate-pulse rounded"
          style={{ background: "hsl(var(--surface-2))" }}
        />
      </header>
      <div className="px-4">
        <div
          className="h-28 animate-pulse rounded-3xl"
          style={{ background: "hsl(var(--surface-1))" }}
        />
      </div>
      <div className="space-y-2 px-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-2xl"
            style={{ background: "hsl(var(--surface-1))" }}
          />
        ))}
      </div>
    </div>
  );
}

function ErrorView({
  title,
  subtitle,
  onHome,
}: {
  title: string;
  subtitle: string;
  onHome: () => void;
}) {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      <ShoppingBag size={40} className="text-white/20" />
      <div>
        <p className="font-semibold text-white">{title}</p>
        <p className="mt-1 text-xs text-white/45">{subtitle}</p>
      </div>
      <button
        onClick={onHome}
        className="rounded-full px-5 py-2 text-sm font-semibold"
        style={{
          background: "hsl(var(--primary))",
          color: "hsl(var(--primary-foreground))",
        }}
      >
        {t("common.toHome")}
      </button>
    </div>
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
