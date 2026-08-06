import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { BrandTile } from "@/components/store/BrandTile";
import { getBrands, type BrandSummary } from "@/lib/catalog";
import { pathFor } from "@/lib/seo";

/**
 * Bento-grid catalog teaser on the landing — a featured brand (2×2) plus
 * smaller brand cards, backed by the live catalog API. Adaptive to any brand
 * count: the feature occupies cols 1–2 / rows 1–2, leaving col 3 for two cards
 * and every further row holding three — so we render the largest multiple of
 * three (capped at 9) and the grid always fills cleanly, however many brands
 * production ends up with. The rest live behind "Весь каталог".
 */
const MAX = 9;

export async function CatalogBento({ locale }: { locale: string }) {
  const t = await getTranslations("web.catalog");

  let all: BrandSummary[] = [];
  try {
    all = await getBrands(locale);
  } catch {
    // API unreachable → skip the teaser rather than break the page.
  }
  if (all.length === 0) return null;

  // Show every brand up to the cap, even when the last row comes out short.
  // Rounding down to a multiple of three filled the grid neatly and silently
  // dropped the tail: at seven brands it rendered six, and the one it cut was
  // Steam — the product with its own dedicated section higher up the same
  // page, promoted there with a "Пополнить Steam" button. A ragged last row
  // costs less than a flagship that cannot be reached from the catalogue block.
  const brands = all.slice(0, MAX);
  const [feature, ...rest] = brands;
  if (!feature) return null;

  return (
    <section id="catalog" className="relative scroll-mt-[88px] py-16 sm:py-24 lg:py-28">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-14 flex items-end justify-between gap-6">
          <div>
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 01 / {t("eyebrow")} ]
            </div>
            <h2 className="font-display mt-3 text-[clamp(2.2rem,4vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
              <span className="block">{t("titleLine1")}</span>
              <span className="text-tx-mute block">{t("titleLine2")}</span>
            </h2>
          </div>
          <Link
            href={pathFor(locale, "/store")}
            className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted rounded-btn hidden h-[44px] items-center gap-2 border px-5 text-sm font-semibold transition sm:inline-flex"
          >
            {t("viewAll")}
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-4 md:auto-rows-[300px] md:grid-cols-3">
          <BrandTile
            brand={feature}
            locale={locale}
            variant="feature"
            className="h-[300px] md:col-span-2 md:row-span-2 md:h-auto"
          />
          {rest.map((brand) => (
            <BrandTile
              key={brand.slug}
              brand={brand}
              locale={locale}
              className="h-[240px] md:h-auto"
            />
          ))}
        </div>

        {/* Mobile gets the "view all" CTA below the grid (the header one is
            desktop-only to keep the heading row uncluttered on phones). */}
        <Link
          href={pathFor(locale, "/store")}
          className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted rounded-btn mt-4 flex h-[48px] items-center justify-center gap-2 border text-sm font-semibold transition sm:hidden"
        >
          {t("viewAll")}
          <ArrowRight size={14} strokeWidth={2.4} />
        </Link>
      </div>
    </section>
  );
}
