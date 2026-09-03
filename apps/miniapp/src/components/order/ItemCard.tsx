import { AnimatePresence, motion } from "framer-motion";
import { Loader2 } from "lucide-react";

import { ArtifactBlock } from "./ArtifactBlock";
import { GiftDeliveryCard } from "./GiftDeliveryCard";
import { isGiftDelivery } from "./order-helpers";
import { TopUpReceipt } from "./TopUpReceipt";

import type { DeliveryOut, OrderOut } from "@/lib/orders";

import { SafeImage } from "@/components/ui/safe-image";
import { useT } from "@/lib/i18n";

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function ItemCard({
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
  const isGift = isGiftDelivery(delivery);

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
          // Checked before `isTopUp`: a Steam gift's product is seeded with
          // `kind="top_up"` (its checkout form matches that shape) and its
          // fulfiller reports `artifact_kind: "topup_receipt"` too — the only
          // signal that this is actually a gift is `artifact.kind === "gift"`
          // on the delivered artifact itself.
          isGift ? (
            <GiftDeliveryCard delivery={delivery} />
          ) : isTopUp ? (
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
