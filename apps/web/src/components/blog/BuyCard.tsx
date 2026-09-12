import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { getBrandDetail } from "@/lib/catalog";
import { isOptimizable } from "@/lib/image";
import { formatUzs, pathFor } from "@/lib/seo";

const CURRENCY = "UZS";

export async function BuyCard({
  brandSlug,
  locale,
}: {
  brandSlug: string;
  locale: string;
}) {
  const brand = await getBrandDetail(brandSlug, locale, CURRENCY);
  if (!brand) return null;
  const t = await getTranslations("web.blog");
  const prices = (brand.products ?? [])
    .map((p) => (p.starting_display_price ? Math.round(Number(p.starting_display_price.amount)) : null))
    .filter((n): n is number => n !== null && Number.isFinite(n));
  const from = prices.length > 0 ? formatUzs(locale, Math.min(...prices)) : null;
  const img = brand.hero_image_url ?? brand.logo_url;

  return (
    <Link
      href={pathFor(locale, `/store/${brand.slug}`)}
      className="border-border hover:border-primary/30 bg-card mt-10 flex overflow-hidden rounded-2xl border transition hover:-translate-y-0.5"
    >
      <div className="bg-card-2 relative hidden w-40 shrink-0 sm:block">
        {img ? (
          <Image
            src={img}
            alt=""
            fill
            unoptimized={!isOptimizable(img)}
            className="object-cover"
            sizes="160px"
          />
        ) : null}
      </div>
      <div className="flex flex-1 flex-col justify-center gap-1 px-5 py-4">
        <p className="font-display text-lg font-semibold tracking-[-0.02em]">{brand.name}</p>
        {from ? (
          <p className="text-tx-mute text-sm">
            <span className="font-semibold">{t("from")}</span>{" "}
            <span className="font-mono font-bold">{from}</span>
          </p>
        ) : null}
        <span className="text-primary mt-1 text-sm font-semibold">{t("buyCta")}</span>
      </div>
    </Link>
  );
}
