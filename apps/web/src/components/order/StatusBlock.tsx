"use client";

import { CheckCircle2, Clock, Loader2, RotateCcw, XCircle, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

/** Statuses with both a ``web.orders.status.*`` label and a ``web.orders.body.*``
 *  explanation; anything else falls back to the raw status code with no body. */
const KNOWN = new Set([
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
  "delivered",
  "failed",
  "cancelled",
  "expired",
  "refunded",
  "partially_refunded",
]);

/** Semantic status tint. `danger` reuses the storefront's existing error rose
 *  (`#FF6B6B`, already used for the not-found line) since the brand palette has
 *  no dedicated red token — everything else maps onto real design tokens. */
type Tone = "success" | "progress" | "pending" | "danger" | "neutral";

const TILE: Record<Tone, string> = {
  success: "bg-primary/12 text-primary ring-primary/25",
  progress: "bg-blue/12 text-blue ring-blue/25",
  pending: "bg-gold/12 text-gold ring-gold/25",
  danger: "bg-[#FF6B6B]/12 text-[#FF6B6B] ring-[#FF6B6B]/25",
  neutral: "bg-muted text-tx-mute ring-border-2",
};

/** Map a status to its tint + icon. `spin` marks the in-motion states whose
 *  loader should rotate (globals.css already stills it under
 *  `prefers-reduced-motion`). */
function toneFor(status: string): { tone: Tone; Icon: LucideIcon; spin: boolean } {
  switch (status) {
    case "delivered":
    case "fulfilled":
      return { tone: "success", Icon: CheckCircle2, spin: false };
    case "paid":
    case "fulfilling":
      return { tone: "progress", Icon: Loader2, spin: true };
    case "pending_payment":
      return { tone: "pending", Icon: Clock, spin: false };
    case "failed":
    case "cancelled":
    case "expired":
      return { tone: "danger", Icon: XCircle, spin: false };
    case "refunded":
    case "partially_refunded":
      return { tone: "neutral", Icon: RotateCcw, spin: false };
    default:
      return { tone: "neutral", Icon: Clock, spin: false };
  }
}

/**
 * Order status hero — a tinted status indicator paired with the display-font
 * heading and explanatory copy for every status (most notably `fulfilling`,
 * which previously showed only the bare status word with no context).
 *
 * `isTopUp` swaps the `delivered` copy for top-up-flavored wording
 * ("Credited" instead of "Delivered") to match the Mini App's phrasing —
 * a top-up never gets "delivered", it gets credited to the account.
 */
export function StatusBlock({ status, isTopUp }: { status: string; isTopUp?: boolean }) {
  const t = useTranslations("web.orders");
  const known = KNOWN.has(status);
  const isDeliveredTopUp = status === "delivered" && Boolean(isTopUp);
  const { tone, Icon, spin } = toneFor(status);

  const heading = isDeliveredTopUp
    ? t("status.deliveredTopup")
    : known
      ? t(`status.${status}`)
      : status;
  const body = isDeliveredTopUp ? t("body.deliveredTopup") : known ? t(`body.${status}`) : null;

  return (
    <div className="flex items-start gap-3.5" role="status" aria-live="polite" aria-atomic="true">
      <span
        className={`flex size-11 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset ${TILE[tone]}`}
        aria-hidden="true"
      >
        <Icon size={22} strokeWidth={2.5} className={spin ? "animate-spin" : undefined} />
      </span>
      <div className="min-w-0 space-y-1 pt-0.5">
        <h2 className="font-display text-foreground text-xl font-bold leading-tight">{heading}</h2>
        {body ? <p className="text-tx-mute text-sm leading-snug">{body}</p> : null}
      </div>
    </div>
  );
}
