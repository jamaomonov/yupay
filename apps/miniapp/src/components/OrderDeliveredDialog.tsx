import { useState } from "react";

import { ReviewsSheet } from "@/components/ReviewsSheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useT } from "@/lib/i18n";
import { useOrder } from "@/lib/orders";
import { useOrderDeliveredDialog } from "@/store/useOrderDeliveredDialog";

/**
 * Global "order delivered" dialog — mounted once in `App.tsx`, opened by
 * `useOrderSocket` on an `order.delivered` WS message
 * (`useOrderDeliveredDialog`). Shows up regardless of which page the customer
 * is currently on (e.g. still browsing Home while a background top-up lands).
 *
 * There is intentionally no "order failed" counterpart: fulfillment failures
 * keep the order at `fulfilling` for admin remediation, never a
 * customer-facing status (DOMAIN RULE) — see `useOrderSocket`.
 */
export function OrderDeliveredDialog() {
  const { t } = useT();
  const { orderId, close } = useOrderDeliveredDialog();
  // Same query key `useOrderSocket` invalidates on `order.delivered`, so this
  // is typically already warm by the time the socket message opens the dialog.
  const order = useOrder(orderId ?? undefined);
  const [reviewFor, setReviewFor] = useState<{ orderId: string; brandSlug: string } | null>(null);

  // Open only once the order has resolved — otherwise the title/body flash for
  // a beat with no rate CTA while `useOrder` is still loading (the CTA depends
  // on the fetched brand). The socket invalidates this key just before opening,
  // so it's usually warm; a cold cache (delivered while browsing elsewhere)
  // fetches first, then opens.
  const isOpen = orderId !== null && Boolean(order.data);
  const brandSlug = order.data?.items[0]?.display?.brand_slug ?? null;

  function handleRate() {
    if (!orderId || !brandSlug) return;
    // Capture the (orderId, brandSlug) pair locally before closing the store
    // — closing sets `orderId` back to null, which would otherwise unmount
    // the review sheet mid-open.
    setReviewFor({ orderId, brandSlug });
    close();
  }

  return (
    <>
      <Dialog
        open={isOpen}
        onOpenChange={(next) => {
          if (!next) close();
        }}
      >
        <DialogContent className="max-w-[340px] text-center sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle>{t("orderResult.deliveredTitle")}</DialogTitle>
            <DialogDescription>{t("orderResult.deliveredBody")}</DialogDescription>
          </DialogHeader>
          {brandSlug && (
            <button
              type="button"
              onClick={handleRate}
              className="bg-primary text-primary-foreground w-full rounded-lg py-2.5 text-sm font-semibold"
            >
              {t("orderResult.rateCta")}
            </button>
          )}
        </DialogContent>
      </Dialog>

      {reviewFor && (
        <ReviewsSheet
          brandSlug={reviewFor.brandSlug}
          formOrderId={reviewFor.orderId}
          onClose={() => {
            setReviewFor(null);
          }}
        />
      )}
    </>
  );
}
