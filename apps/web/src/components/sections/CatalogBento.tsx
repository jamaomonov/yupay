import { ArrowRight, BadgeCheck, Gamepad2, Gift, LayoutGrid, Wallet } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { LucideIcon } from "lucide-react";

import { BrandIcon } from "@/components/store/BrandIcon";
import { byPopularity } from "@/lib/brand-order";
import { getBrands, getCategories, type BrandSummary, type CategoryOut } from "@/lib/catalog";
import { headingStyles } from "@/lib/heading";
import { pathFor } from "@/lib/seo";

/**
 * The landing's catalogue teaser, one panel per catalogue (owner, 2026-11-24:
 * "make it clear we have two catalogues, and show a few brands from each").
 *
 * Each panel answers, top to bottom: which catalogue (name from the API), what
 * the buyer gets (one line), a few recognisable brands (the same square
 * `BrandIcon` as /store), and a full-width way into the filtered catalogue.
 * Panels follow the API's category order and only categories with brands
 * render, so the block works for any number of them — it is drawn for two.
 *
 * Brands per panel: 4 on a phone (one row), 6 when panels are stacked on a
 * tablet, 5 side by side from `lg`. Extra brands are hidden per breakpoint
 * rather than dropped, so the order is one list for every width.
 */
const SHOWN_MAX = 6;

function displayFor(index: number): string {
  if (index < 4) return "flex";
  if (index < 5) return "hidden sm:flex";
  return "hidden sm:flex lg:hidden";
}

/** The category's `icon` is a lucide name chosen in the admin; unknown → a grid. */
const ICONS: Record<string, LucideIcon> = {
  wallet: Wallet,
  gift: Gift,
  "gamepad-2": Gamepad2,
  "badge-check": BadgeCheck,
};

interface Shelf {
  category: CategoryOut;
  brands: BrandSummary[];
  total: number;
}

function shelvesOf(categories: CategoryOut[], brands: BrandSummary[]): Shelf[] {
  const ordered = byPopularity(brands);
  return categories
    .map((category) => {
      const own = ordered.filter((b) => b.category_slug === category.slug);
      return { category, brands: own.slice(0, SHOWN_MAX), total: own.length };
    })
    .filter((shelf) => shelf.total > 0);
}

export async function CatalogBento({ locale }: { locale: string }) {
  const t = await getTranslations("web.catalog");

  let shelves: Shelf[] = [];
  try {
    const [categories, brands] = await Promise.all([getCategories(locale), getBrands(locale)]);
    shelves = shelvesOf(categories, brands);
  } catch {
    // API unreachable → skip the teaser rather than break the page.
  }
  if (shelves.length === 0) return null;

  const storeHref = pathFor(locale, "/store");

  return (
    <section id="catalog" className="relative scroll-mt-[88px] py-14 sm:py-20">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-8 flex items-end justify-between gap-6 sm:mb-12">
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
            href={storeHref}
            className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted rounded-btn focus-visible:ring-primary focus-visible:ring-offset-bg hidden h-[44px] shrink-0 items-center gap-2 border px-5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 sm:inline-flex"
          >
            {t("viewAll")}
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-2">
          {shelves.map((shelf) => (
            <CatalogPanel key={shelf.category.slug} shelf={shelf} locale={locale} />
          ))}
        </div>

        <Link
          href={storeHref}
          className="text-tx-mute hover:text-foreground focus-visible:ring-primary mx-auto mt-6 flex h-11 w-fit items-center gap-2 rounded-lg px-3 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 sm:hidden"
        >
          {t("viewAll")}
          <ArrowRight size={14} strokeWidth={2.4} />
        </Link>
      </div>
    </section>
  );
}

async function CatalogPanel({ shelf, locale }: { shelf: Shelf; locale: string }) {
  const t = await getTranslations("web.catalog");
  const { category, brands, total } = shelf;
  const Icon = (category.icon ? ICONS[category.icon] : undefined) ?? LayoutGrid;
  const fallbackKey = `kinds.${category.slug}`;
  const blurb = category.description ?? (t.has(fallbackKey) ? t(fallbackKey) : null);
  const headingId = `catalog-${category.slug}`;

  return (
    <article
      aria-labelledby={headingId}
      className="border-border bg-card/60 relative isolate flex flex-col overflow-hidden rounded-[24px] border"
    >
      {/* The catalogue's mark, oversized and faint: tells the panels apart at a glance. */}
      <Icon
        aria-hidden
        size={150}
        strokeWidth={1.25}
        className="text-primary pointer-events-none absolute -right-10 -top-10 -z-10 opacity-[0.045] sm:-right-6 sm:-top-6"
      />
      <header className="flex items-start gap-4 px-5 pb-5 pt-5 sm:px-7 sm:pt-7">
        <span
          aria-hidden
          className="border-primary/25 bg-primary/10 text-primary rounded-btn flex h-11 w-11 shrink-0 items-center justify-center border"
        >
          <Icon size={20} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-tx-dim font-mono text-[11px] font-semibold uppercase tracking-[0.14em]">
            {t("brandCount", { count: total })}
          </div>
          <h3
            id={headingId}
            className="font-display text-foreground mt-1 text-[22px] font-extrabold leading-tight tracking-[-0.01em] sm:text-[26px]"
          >
            {category.name}
          </h3>
          {blurb && <p className="text-tx-mute mt-1.5 text-sm leading-snug">{blurb}</p>}
        </div>
      </header>

      <div className="grid grid-cols-4 gap-x-3 gap-y-5 px-5 pb-6 sm:grid-cols-6 sm:gap-x-4 sm:px-7 lg:grid-cols-5">
        {brands.map((brand, i) => (
          <BrandIcon key={brand.slug} brand={brand} locale={locale} className={displayFor(i)} />
        ))}
      </div>

      <Link
        href={`${pathFor(locale, "/store")}?cat=${encodeURIComponent(category.slug)}`}
        aria-label={t("openAria", { name: category.name })}
        className="border-border text-foreground hover:bg-muted focus-visible:bg-muted focus-visible:ring-primary group mt-auto flex min-h-[56px] items-center justify-between gap-3 border-t px-5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset sm:px-7"
      >
        <span>{t("open")}</span>
        <span className="bg-primary text-primary-foreground flex h-8 w-8 items-center justify-center rounded-full transition group-hover:translate-x-0.5">
          <ArrowRight size={16} strokeWidth={2.6} aria-hidden />
        </span>
      </Link>
    </article>
  );
}
