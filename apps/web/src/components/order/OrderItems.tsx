"use client";

import { formatMoney } from "@yupay/utils";
import Image from "next/image";
import { useLocale, useTranslations } from "next-intl";

import type { OrderItemOut } from "@/lib/orders-types";

import { isOptimizable } from "@/lib/image";

/** Decimal-safe line total in USD major units ("11.30" × qty), computed in
 *  integer cents so 0.1 × 3 never drifts to 0.30000000000000004. */
function lineTotalUsd(item: OrderItemOut): string {
  const cents = Math.round(Number.parseFloat(item.unit_price_usd) * 100) * item.qty;
  return (cents / 100).toFixed(2);
}

/** Brand · amount/denomination. A variable-amount top-up (Steam wallet) stores a
 *  placeholder denomination ("Любая сумма" / "Any amount") that tells the
 *  customer nothing — for those the "·" segment becomes the credited USD
 *  amount, so the line reads "Steam · $11.30". A fixed denomination ("60 UC",
 *  "820 UC") is kept verbatim ("PUBG Mobile · 60 UC"). Region is appended
 *  when present. */
function itemHeadline(item: OrderItemOut, locale: string): string {
  const d = item.display;
  if (!d) return item.sku_id;
  const amount = d.variable_amount ? formatMoney(lineTotalUsd(item), "USD", locale) : null;
  const middle = amount ?? d.denomination ?? d.product_name;
  const parts = [d.brand_name, middle, d.region ?? undefined].filter(Boolean);
  return parts.join(" · ");
}

/** Non-empty scalar fields the customer entered at checkout (steam_login,
 *  player_id, server, …). This is the buyer's OWN input already on the order —
 *  the target account the top-up was credited to, NOT a delivered artifact. */
function checkoutFields(fd: Record<string, unknown>): [string, string][] {
  return Object.entries(fd)
    .filter(([, v]) => typeof v === "number" || (typeof v === "string" && v.trim() !== ""))
    .map(([k, v]) => [k, String(v)] as [string, string]);
}

/** snake_case / kebab-case field name → readable "Player Id". */
function humanize(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
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
        // Same rule as the rest of the catalogue art: this thumbnail can point
        // at a third-party host, and this call site never had the guard.
        unoptimized={!isOptimizable(d.image_url)}
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
  const locale = useLocale();
  if (items.length === 0) return null;
  return (
    <section className="space-y-2.5">
      <h3 className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
        {t("itemsTitle")}
      </h3>
      <ul className="space-y-2">
        {items.map((item) => {
          const fields = checkoutFields(item.fulfillment_data);
          return (
            <li key={item.id} className="border-border bg-card-2 rounded-xl border p-3">
              <div className="flex items-center gap-3">
                <ItemThumb item={item} />
                <span className="text-foreground min-w-0 flex-1 truncate text-sm font-semibold">
                  {itemHeadline(item, locale)}
                </span>
                {item.qty > 1 ? (
                  <span className="border-border-2 text-tx-mute rounded-btn shrink-0 border px-2 py-0.5 text-xs font-medium tabular-nums">
                    {t("qty")}: {item.qty}
                  </span>
                ) : null}
              </div>

              {fields.length > 0 ? (
                <dl className="border-border mt-3 space-y-1.5 border-t pt-3">
                  {fields.map(([key, value]) => (
                    <div key={key} className="flex items-baseline justify-between gap-3 text-sm">
                      <dt className="text-tx-mute shrink-0">
                        {t.has(`receipt.${key}`) ? t(`receipt.${key}`) : humanize(key)}
                      </dt>
                      <dd className="text-foreground max-w-[62%] truncate text-right font-mono">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
