import { RateAsk } from "@/components/review/RateAsk";
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
 * `useOrderSocket` on an `order.delivered` WS message. Stars sit in the
 * dialog itself so rating is one tap, not a second sheet.
 */
export function OrderDeliveredDialog() {
  const { t } = useT();
  const { orderId, close } = useOrderDeliveredDialog();
  const order = useOrder(orderId ?? undefined);

  const isOpen = orderId !== null && Boolean(order.data);
  const display = order.data?.items[0]?.display;
  const brandSlug = display?.brand_slug ?? null;

  return (
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
        {orderId && brandSlug && (
          <RateAsk
            key={orderId}
            orderId={orderId}
            brandSlug={brandSlug}
            brandName={display?.brand_name ?? null}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
