"use client";

import { formatMoney } from "@yupay/utils";
import { Receipt } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { OrderOut } from "@/lib/orders-types";

import { isOptimizable } from "@/lib/image";
import { isTopUpOrder, orderSubtitle, orderTitle, STATUS_CLS } from "@/lib/order-display";

/**
 * Order-history card shared by the logged-in list (`account/orders`) and the
 * guest (localStorage) list, mirroring the Mini App's `OrdersTab` row look
 * (`apps/miniapp/src/pages/History.tsx`): a 44px brand image, a bold
 * "brand · denomination" title, a muted date/subtitle line, the paid amount,
 * and a colored status chip.
 */
export function OrderCard({
  order,
  locale,
  href,
}: {
  order: OrderOut;
  locale: string;
  href: string;
}) {
  const t = useTranslations("web.orders");
  const img = order.items[0]?.display?.image_url ?? null;

  const cls = STATUS_CLS[order.status] ?? "bg-tx-dim/15 text-tx-dim";
  // A delivered top-up order reads "Credited" rather than "Delivered" —
  // matches the wording StatusBlock uses on the order-detail page.
  const isDeliveredTopUp = order.status === "delivered" && isTopUpOrder(order);
  const label = isDeliveredTopUp
    ? t("status.deliveredTopup")
    : order.status in STATUS_CLS
      ? t(`status.${order.status}`)
      : // Same reasoning as `StatusBlock`'s heading: a status this build has
        // not met is described, not printed.
        t("status.unknown");

  const dateText = new Intl.DateTimeFormat(locale).format(new Date(order.created_at));
  const subtitleText = orderSubtitle(order);
  const subtitle = subtitleText ? `${dateText} · ${subtitleText}` : dateText;

  return (
    <Link
      href={href}
      className="border-border bg-card hover:border-tx-dim flex items-center gap-3 rounded-2xl border p-3.5 transition"
    >
      <span className="bg-muted relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl">
        {img ? (
          <Image
            src={img}
            alt=""
            fill
            unoptimized={!isOptimizable(img)}
            sizes="44px"
            className="object-contain"
          />
        ) : (
          <Receipt size={18} className="text-tx-dim" aria-hidden="true" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-sm font-bold">
          {orderTitle(order, t("fallbackTitle", { id: order.id.slice(0, 8) }))}
        </p>
        <p className="text-tx-dim mt-0.5 truncate text-[11px]">{subtitle}</p>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="text-primary text-sm font-bold">
          {formatMoney(order.total_charged, order.currency, locale)}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{label}</span>
      </div>
    </Link>
  );
}
