"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Brand, Sku } from "@/lib/types";

import { formatPrice, perHundred } from "@/lib/money";

/**
 * A brand's denominations as price-list rows, grouped by product.
 *
 * One line per denomination — name, then price at the right edge — the way
 * a price list reads. The tall tiles with an empty picture box on every gift
 * card were half air. A product heading only where it says something the
 * brand name does not: the import named most products after their brand.
 */
export function SkuRows({
  brand,
  selected,
  onPick,
}: {
  brand: Brand;
  selected: Sku | null;
  onPick: (sku: Sku) => void;
}) {
  const t = useTranslations("merchant.catalog");
  return (
    <div className="space-y-6">
      {brand.products.map((item) => (
        <section key={item.product_id}>
          {/* One product: its name is already the subtitle under the brand. */}
          {brand.products.length > 1 && (
            <h2 className="text-tx-mute text-sm font-medium">{item.name}</h2>
          )}
          {/* One line per denomination — name, then price at the right
          edge, the way a price list reads. The tall tiles with an
          empty picture box on every gift card were half air. */}
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {item.skus.map((sku) => {
              const price = sku.kind === "fixed" ? sku.price_usd : sku.unit_price_usd;
              const active = selected?.sku_id === sku.sku_id;
              return (
                <button
                  key={sku.sku_id}
                  type="button"
                  onClick={() => {
                    onPick(sku);
                  }}
                  aria-pressed={active}
                  className={`flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2 text-left transition ${
                    active
                      ? "border-primary bg-card-2"
                      : "border-border bg-card hover:border-border-2"
                  }`}
                >
                  {sku.image_url !== null && (
                    <span className="bg-card-2 border-border h-9 w-9 shrink-0 overflow-hidden rounded-md border">
                      {/* eslint-disable-next-line @next/next/no-img-element -- an
                      operator-entered absolute URL on a host we do not
                      control; same reason the brand logo above uses <img>. */}
                      <img src={sku.image_url} alt="" className="h-full w-full object-contain" />
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{sku.name}</span>
                  <span className="flex shrink-0 items-baseline gap-1 font-mono text-sm">
                    {price && sku.kind === "unit" && perHundred(price) !== null ? (
                      <>
                        ${perHundred(price)}
                        <span className="text-tx-dim font-sans text-[11px]">{t("perHundred")}</span>
                      </>
                    ) : price ? (
                      `$${formatPrice(price)}`
                    ) : (
                      "—"
                    )}
                    {sku.kind === "amount" && price && (
                      <span className="text-tx-dim font-sans text-[11px]">{t("perDollar")}</span>
                    )}
                  </span>
                  {active && (
                    <span
                      aria-label={t("selected")}
                      className="bg-primary text-primary-foreground flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                    >
                      <Check size={12} strokeWidth={3} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
