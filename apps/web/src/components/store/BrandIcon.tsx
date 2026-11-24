import { Star } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { BrandSummary } from "@/lib/catalog";

import { brandPath } from "@/lib/brand-href";
import { isOptimizable } from "@/lib/image";
import { pathFor } from "@/lib/seo";

/**
 * The catalogue's brand tile: a square brand mark with the name under it, the
 * way an app shelf reads. The whole catalogue fits a screen or two, so a
 * buyer scans it instead of scrolling past key art (owner, 2026-11-24).
 *
 * The square is the brand's `logo_url` (square marks, 256–700 px); a brand
 * without one falls back to its key art cropped to the square, then to its
 * initial on the accent colour, so a missing upload never leaves a hole.
 * Rendered as the direct grid child of `StoreFilter` — `flex` gives the
 * anchor a box, see the note there.
 */
export async function BrandIcon({ brand, locale }: { brand: BrandSummary; locale: string }) {
  const ts = await getTranslations("web.store");
  const img = brand.logo_url ?? brand.hero_image_url;
  const accent = brand.accent_color ?? "#AAFF33";

  return (
    <Link
      href={pathFor(locale, brandPath(brand.slug))}
      className="focus-visible:ring-primary focus-visible:ring-offset-bg group flex min-w-0 flex-col items-center rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-4"
    >
      <span className="border-border bg-card group-hover:ring-primary/70 relative block aspect-square w-full overflow-hidden rounded-[22%] border transition group-hover:ring-2">
        {img ? (
          <Image
            src={img}
            alt=""
            fill
            unoptimized={!isOptimizable(img)}
            sizes="(max-width: 640px) 30vw, (max-width: 1024px) 18vw, 128px"
            className="object-cover"
          />
        ) : (
          <span
            aria-hidden
            className="font-display absolute inset-0 flex items-center justify-center text-[clamp(1.5rem,5vw,2.25rem)] font-extrabold text-white"
            style={{ background: `linear-gradient(135deg, ${accent}99, #0A0D1A)` }}
          >
            {brand.name.slice(0, 1)}
          </span>
        )}
        {brand.maintenance && (
          <span className="absolute inset-x-0 bottom-0 bg-black/75 py-1 text-center text-[10px] font-bold text-white">
            {ts("maintenance")}
          </span>
        )}
      </span>
      <span className="text-foreground mt-2.5 line-clamp-2 w-full text-center text-[13px] font-semibold leading-tight sm:text-sm">
        {brand.name}
      </span>
      {/* Real ratings only — `count > 0` is enforced by the API shape. */}
      {brand.rating && brand.rating.count > 0 && (
        <span className="text-tx-dim mt-1 inline-flex items-center gap-1 text-[11px] font-semibold">
          <Star size={11} className="fill-gold text-gold" aria-hidden />
          {brand.rating.avg.toFixed(1)}
        </span>
      )}
    </Link>
  );
}
