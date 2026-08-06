import { ArrowRight, Star } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { BrandSummary } from "@/lib/catalog";

import { pathFor } from "@/lib/seo";

/**
 * The brand tile — key art, name, rating, maintenance badge — used both in the
 * catalogue grid and in the home page's bento.
 *
 * It existed twice. The copies had drifted: different scrim opacities
 * (0.88/0.3/82% against 0.9/0.45/80%), 24px against 26px titles, a text-shadow
 * on one only, and — the part that actually cost something — the rating was
 * drawn by the catalogue copy alone, so the same brand showed its stars on
 * /store and hid them on the home page, which is where most first-time
 * visitors meet it.
 *
 * Reconciled here: the stronger scrim plus the text-shadow (legibility over
 * arbitrary key art wins), the rating always, and one title scale. The
 * `feature` variant drops to 32px below `sm` — at 48px it climbed into the
 * artwork's own logo on a phone.
 */
export async function BrandTile({
  brand,
  locale,
  variant = "default",
  className = "",
}: {
  brand: BrandSummary;
  locale: string;
  /** `feature` is the oversized bento cell; everything else is `default`. */
  variant?: "feature" | "default";
  /** Grid placement and height, supplied by whichever layout hosts the tile. */
  className?: string;
}) {
  const ts = await getTranslations("web.store");
  const img = brand.hero_image_url ?? brand.logo_url;
  const accent = brand.accent_color ?? "#AAFF33";
  const featured = variant === "feature";

  return (
    <Link
      href={pathFor(locale, `/store/${brand.slug}`)}
      className={`border-border hover:border-primary/30 focus-visible:ring-primary group relative isolate overflow-hidden rounded-xl border transition hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset ${className}`}
    >
      {img ? (
        <Image
          src={img}
          alt={brand.name}
          fill
          unoptimized
          sizes={
            featured
              ? "(max-width: 768px) 100vw, 540px"
              : "(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 300px"
          }
          className="object-cover transition duration-500 group-hover:scale-[1.04]"
        />
      ) : (
        <div
          aria-hidden
          className="absolute inset-0"
          style={{ background: `linear-gradient(135deg, ${accent}55, #0A0D1A)` }}
        />
      )}
      <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.9)_0%,rgba(0,0,0,0.45)_45%,transparent_80%)]" />

      {brand.maintenance && (
        <span className="rounded-btn absolute left-4 top-4 z-10 inline-flex bg-black/60 px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em] text-white backdrop-blur">
          {ts("maintenance")}
        </span>
      )}

      <div className="absolute inset-x-5 bottom-5 z-10">
        {/* Real ratings only — `count > 0` is enforced by the API shape, and
            nothing here invents an average. */}
        {brand.rating && brand.rating.count > 0 && (
          <div className="mb-1.5 inline-flex items-center gap-1 text-[11px] font-bold text-white [text-shadow:0_1px_6px_rgba(0,0,0,0.7)]">
            <Star size={12} className="fill-gold text-gold" />
            {brand.rating.avg.toFixed(1)}
            <span className="font-semibold text-white/60">({brand.rating.count})</span>
          </div>
        )}
        <div className="flex items-end justify-between gap-3">
          <div
            className={`font-display font-extrabold leading-none tracking-[-0.025em] text-white [text-shadow:0_2px_10px_rgba(0,0,0,0.6)] ${
              featured ? "text-[32px] sm:text-[48px]" : "text-[26px]"
            }`}
          >
            {brand.name}
          </div>
          <div className="border-white/18 group-hover:bg-primary rounded-btn flex h-10 w-10 shrink-0 items-center justify-center border bg-black/45 backdrop-blur transition">
            <ArrowRight
              size={16}
              strokeWidth={2.4}
              className="group-hover:text-primary-foreground text-white transition"
            />
          </div>
        </div>
      </div>
    </Link>
  );
}
