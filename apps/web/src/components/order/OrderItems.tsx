"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import type { OrderItemOut } from "@/lib/orders-types";

function itemHeadline(item: OrderItemOut): string {
  const d = item.display;
  if (!d) return item.sku_id;
  const parts = [d.brand_name, d.denomination ?? d.product_name, d.region ?? undefined].filter(
    Boolean,
  );
  return parts.join(" · ");
}

/** Brand thumbnail, or a lettered fallback tile when a SKU has no image. */
function ItemThumb({ item }: { item: OrderItemOut }) {
  const d = item.display;
  if (d?.image_url) {
    return (
      <Image
        src={d.image_url}
        alt=""
        width={44}
        height={44}
        className="border-border size-11 shrink-0 rounded-lg border object-cover"
      />
    );
  }
  const initial = d?.brand_name[0]?.toUpperCase() ?? "?";
  return (
    <span className="bg-muted text-tx-dim border-border flex size-11 shrink-0 items-center justify-center rounded-lg border text-sm font-bold">
      {initial}
    </span>
  );
}

export function OrderItems({ items }: { items: OrderItemOut[] }) {
  const t = useTranslations("web.orders");
  if (items.length === 0) return null;
  return (
    <section className="space-y-2.5">
      <h3 className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
        {t("itemsTitle")}
      </h3>
      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={item.id}
            className="border-border bg-card-2 flex items-center gap-3 rounded-xl border p-3"
          >
            <ItemThumb item={item} />
            <span className="text-foreground min-w-0 flex-1 truncate text-sm font-semibold">
              {itemHeadline(item)}
            </span>
            {item.qty > 1 ? (
              <span className="border-border-2 text-tx-mute rounded-btn shrink-0 border px-2 py-0.5 text-xs font-medium tabular-nums">
                {t("qty")}: {item.qty}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
