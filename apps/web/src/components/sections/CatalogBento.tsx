import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { BrandIcon } from "@/components/store/BrandIcon";
import { byPopularity } from "@/lib/brand-order";
import { getBrands, type BrandSummary } from "@/lib/catalog";
import { headingStyles } from "@/lib/heading";
import { pathFor } from "@/lib/seo";

/**
 * The landing's catalogue teaser: the same square brand icons as /store, two
 * rows of them, and a last tile into the full catalogue (owner, 2026-11-24 —
 * the old bento spent a screen on three pieces of key art).
 *
 * The last tile always closes a full row: 8 brands + it on a phone (3×3),
 * 11 + it from `sm` (4×3 and 6×2), 15 + it from `lg` (8×2). Brands past a
 * breakpoint's count are hidden there rather than dropped, so the order is one
 * list for every width.
 */
const PHONE = 8;
const TABLET = 11;
const DESKTOP = 15;

function displayFor(index: number): string {
  if (index < PHONE) return "flex";
  if (index < TABLET) return "hidden sm:flex";
  return "hidden lg:flex";
}

export async function CatalogBento({ locale }: { locale: string }) {
  const t = await getTranslations("web.catalog");

  let all: BrandSummary[] = [];
  try {
    all = await getBrands(locale);
  } catch {
    // API unreachable → skip the teaser rather than break the page.
  }
  if (all.length === 0) return null;

  const brands = byPopularity(all).slice(0, DESKTOP);
  // How many the «all» tile stands for, per width.
  const left = (shown: number): number => all.length - Math.min(shown, brands.length);

  return (
    <section id="catalog" className="relative scroll-mt-[88px] py-14 sm:py-20">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-10 flex items-end justify-between gap-6 sm:mb-12">
          <div>
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 01 / {t("eyebrow")} ]
            </div>
            <h2 className={headingStyles("display", "mt-3")}>
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

        <div className="grid grid-cols-3 gap-x-3 gap-y-6 sm:grid-cols-4 sm:gap-x-5 md:grid-cols-6 lg:grid-cols-8">
          {brands.map((brand, i) => (
            <BrandIcon key={brand.slug} brand={brand} locale={locale} className={displayFor(i)} />
          ))}
          <Link
            href={pathFor(locale, "/store")}
            className="focus-visible:ring-primary focus-visible:ring-offset-bg group flex min-w-0 flex-col items-center rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-4"
          >
            <span className="border-border-2 bg-muted group-hover:border-primary/70 text-foreground relative flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-[22%] border border-dashed transition">
              <span className="font-display text-[clamp(1.25rem,4vw,1.75rem)] font-extrabold leading-none">
                {left(PHONE) > 0 && <span className="sm:hidden">+{left(PHONE)}</span>}
                {left(TABLET) > 0 && (
                  <span className="hidden sm:inline lg:hidden">+{left(TABLET)}</span>
                )}
                {left(DESKTOP) > 0 && <span className="hidden lg:inline">+{left(DESKTOP)}</span>}
              </span>
              <ArrowRight size={16} strokeWidth={2.4} className="text-primary" aria-hidden />
            </span>
            <span className="text-foreground mt-2.5 line-clamp-2 w-full text-center text-[13px] font-semibold leading-tight sm:text-sm">
              {t("viewAll")}
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}
