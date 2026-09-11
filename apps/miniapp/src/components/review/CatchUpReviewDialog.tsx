import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "wouter";

import { RateAsk } from "./RateAsk";

import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import {
  catchUpAllowedOn,
  dismissReviewAsk,
  isReviewAskDismissed,
  parseReviewLaunchParam,
} from "@/lib/review-ask";
import { getPendingAsk } from "@/lib/reviews";
import { getWebApp } from "@/lib/telegram";
import { useOrderDeliveredDialog } from "@/store/useOrderDeliveredDialog";
import { useOverlay } from "@/store/useOverlay";

function launchedIntoReview(): boolean {
  return (
    parseReviewLaunchParam(
      window.location.search,
      getWebApp()?.initDataUnsafe.start_param,
    ) !== null
  );
}

/**
 * Next-session catch-up: after the buyer left to check the game, ask on the
 * next calm screen (home / history). Server-gated to 2h–14d old deliveries.
 */
export function CatchUpReviewDialog() {
  const { t } = useT();
  const me = useMe();
  const [path] = useLocation();
  const liveDelivery = useOrderDeliveredDialog((s) => s.orderId);
  const [dismissed, setDismissed] = useState(false);
  const calm =
    Boolean(me.data) &&
    liveDelivery === null &&
    catchUpAllowedOn(path) &&
    !launchedIntoReview();

  const pending = useQuery({
    queryKey: ["review-pending-ask"],
    queryFn: getPendingAsk,
    enabled: calm,
  });

  const ask = pending.data ?? null;
  const openOverlay = useOverlay((s) => s.open);
  const closeOverlay = useOverlay((s) => s.close);
  const visible =
    calm &&
    !dismissed &&
    ask !== null &&
    !isReviewAskDismissed(ask.order_id);

  useEffect(() => {
    if (!visible) return;
    openOverlay();
    return closeOverlay;
  }, [visible, openOverlay, closeOverlay]);

  if (!visible || ask === null) return null;

  const orderId = ask.order_id;
  function close() {
    dismissReviewAsk(orderId);
    setDismissed(true);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-modal="true">
      <button aria-label="close" className="absolute inset-0 bg-black/60" onClick={close} />
      <div className="relative w-full rounded-t-2xl bg-[hsl(var(--card))] p-5">
        <div className="mb-3 flex justify-end">
          <button type="button" aria-label="close" onClick={close} className="text-white/50">
            <X size={20} />
          </button>
        </div>
        <RateAsk
          orderId={ask.order_id}
          brandSlug={ask.brand_slug}
          brandName={ask.brand_name}
        />
        <button type="button" onClick={close} className="mt-3 w-full py-2 text-sm text-white/50">
          {t("reviews.later")}
        </button>
      </div>
    </div>
  );
}
