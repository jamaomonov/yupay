"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { ReviewAsk } from "@/components/store/ReviewAsk";
import { useAuth } from "@/lib/auth";
import { dismissReviewAsk, isReviewAskDismissed } from "@/lib/review-ask";
import { getPendingAsk, type PendingAsk } from "@/lib/reviews";
import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";

/**
 * Next-session catch-up: a delivered order the buyer left to verify, asked
 * about when they come back (2h+ old, server-gated). Suppressed while the
 * live delivered modal is open, on the order page itself (which already has
 * the form), and on the payment-return route.
 *
 * The pending-ask query goes null the moment a star is POSTed; we snapshot
 * the row so the follow-up (chips + text + Submit) is not unmounted.
 */
export function CatchUpReviewModal() {
  const t = useTranslations("web.orderResult");
  const tr = useTranslations("web.brandReviews");
  const { user } = useAuth();
  const deliveredOrderId = useOrderDeliveredModal((s) => s.orderId);
  const pathname = usePathname();
  const [dismissed, setDismissed] = useState(false);
  const [held, setHeld] = useState<PendingAsk | null>(null);
  const [rated, setRated] = useState(false);

  const pending = useQuery({
    queryKey: ["review-pending-ask"],
    queryFn: getPendingAsk,
    enabled: Boolean(user) && deliveredOrderId === null,
  });

  useEffect(() => {
    if (pending.data && held === null) setHeld(pending.data);
  }, [pending.data, held]);

  const ask = held ?? pending.data ?? null;
  if (!user || deliveredOrderId !== null || dismissed || ask === null) return null;
  if (isReviewAskDismissed(ask.order_id)) return null;
  if (pathname.includes("/checkout")) return null;
  if (pathname.includes(`/orders/${ask.order_id}`)) return null;

  const orderId = ask.order_id;
  function close() {
    dismissReviewAsk(orderId);
    setDismissed(true);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={tr("askTitle")}
      className="fixed inset-0 z-[90] flex items-center justify-center p-4"
    >
      {rated ? (
        <div className="bg-bg/80 absolute inset-0 backdrop-blur-sm" />
      ) : (
        <button
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          onClick={close}
          className="bg-bg/80 absolute inset-0 backdrop-blur-sm"
        />
      )}
      <div className="border-border bg-card relative z-10 w-full max-w-[420px] rounded-2xl border p-7 outline-none">
        <button
          type="button"
          onClick={close}
          aria-label={t("close")}
          className="text-tx-mute hover:bg-muted hover:text-foreground absolute right-3 top-3 flex h-10 w-10 items-center justify-center rounded-full transition"
        >
          <X size={18} />
        </button>
        <ReviewAsk
          variant="bare"
          orderId={ask.order_id}
          brandSlug={ask.brand_slug}
          brandName={ask.brand_name}
          onRated={() => {
            setHeld(ask);
            setRated(true);
          }}
          onFinished={close}
        />
        {!rated && (
          <button type="button" onClick={close} className="text-tx-mute mt-4 text-sm">
            {tr("later")}
          </button>
        )}
      </div>
    </div>
  );
}
