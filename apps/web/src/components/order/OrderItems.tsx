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

export function OrderItems({ items }: { items: OrderItemOut[] }) {
  const t = useTranslations("web.orders");
  if (items.length === 0) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-muted-foreground text-sm font-medium">{t("itemsTitle")}</h3>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-3 rounded-lg border p-2">
            {item.display?.image_url ? (
              <Image
                src={item.display.image_url}
                alt=""
                width={40}
                height={40}
                className="h-10 w-10 rounded object-cover"
              />
            ) : null}
            <span className="flex-1 text-sm">{itemHeadline(item)}</span>
            {item.qty > 1 ? (
              <span className="text-muted-foreground text-xs">
                {t("qty")}: {item.qty}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
