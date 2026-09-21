import { motion } from "framer-motion";
import { CheckCircle2, ExternalLink, HeadphonesIcon, Loader2, XCircle } from "lucide-react";

import type { OrderOut, ProductKind } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { translate } from "@/lib/i18n/core";

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

function formatElapsed(seconds: number): string {
  if (seconds < 60) return translate("success.elapsedSec", { n: seconds });
  const minutes = Math.floor(seconds / 60);
  return translate("success.elapsedMin", { n: minutes });
}

export interface StageCopy {
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

export function stageFor(order: OrderOut): StageCopy {
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
    case "failed":
      return {
        title: translate("success.stage.failedTitle"),
        subtitle: translate("success.stage.failedSub"),
      };
    case "partially_refunded":
      return {
        title: translate("success.stage.partiallyRefundedTitle"),
        subtitle: translate("success.stage.partiallyRefundedSub"),
      };
    default:
      // Exhaustive over `OrderStatus` — `never` makes a status added to the
      // union without a case here a compile error. The branch still RETURNS
      // rather than throwing, and that is the whole lesson of this bug: with
      // no default at all the function quietly returned `undefined`, and the
      // order page died on `stage.subtitle` for every `failed` order. A
      // status we have never heard of should read as "we are looking at it",
      // not as a white screen.
      return assertNever(order.status);
  }
}

/**
 * Compile-time exhaustiveness, runtime safety net.
 *
 * Deliberately neutral: a status this build has not heard of says only that
 * the order is being looked at, with no second line. Naming the raw status
 * would put an enum in front of a buyer, and guessing at copy for it would
 * risk telling somebody their money is coming back when it is not.
 */
function assertNever(_status: never): StageCopy {
  return { title: translate("success.stage.unknownTitle"), subtitle: "" };
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

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function StatusCard({
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
