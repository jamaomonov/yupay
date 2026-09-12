import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { isOptimizable } from "@/lib/image";
import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";

import type { BrandDetail } from "@/lib/catalog";

export function buyFromPrice(brand: BrandDetail, locale: string): string | null {
  const prices = (brand.products ?? [])
    .map((p) => (p.starting_display_price ? Math.round(Number(p.starting_display_price.amount)) : null))
    .filter((n): n is number => n !== null && Number.isFinite(n));
  return prices.length > 0 ? formatUzs(locale, Math.min(...prices)) : null;
}

export async function BuyCard({
  brand,
  locale,
}: {
  brand: BrandDetail;
  locale: string;
}) {
  const t = await getTranslations("web.blog");
  const from = buyFromPrice(brand, locale);
  const img = brand.hero_image_url ?? brand.logo_url;
  const href = pathFor(locale, `/store/${brand.slug}`);

  return (
    <Link
      href={href}
      className="border-border hover:border-primary/30 bg-card mt-10 hidden overflow-hidden rounded-2xl border transition hover:-translate-y-0.5 sm:flex"
    >
      <div className="bg-card-2 relative w-40 shrink-0">
        {img ? (
          <Image
            src={img}
            alt={brand.name}
            fill
            unoptimized={!isOptimizable(img)}
            className="object-cover"
            sizes="160px"
          />
        ) : null}
      </div>
      <div className="flex flex-1 flex-col justify-center gap-2 px-5 py-4">
        <p className="font-display text-lg font-semibold tracking-[-0.02em]">{brand.name}</p>
        {from ? (
          <p className="text-tx-mute text-sm">
            <span className="font-semibold">{t("from")}</span>{" "}
            <span className="font-mono font-bold">{from}</span>
          </p>
        ) : null}
        <span className={buttonStyles({ size: "sm", className: "mt-1 w-fit" })}>{t("buyCta")}</span>
      </div>
    </Link>
  );
}
