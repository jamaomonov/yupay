import { BadgeCheck, ChevronRight, Gamepad2, Gift, LayoutGrid, Wallet } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { LucideIcon } from "lucide-react";

import { BrandIcon } from "@/components/store/BrandIcon";
import { byPopularity } from "@/lib/brand-order";
import { getBrands, getCategories, type BrandSummary, type CategoryOut } from "@/lib/catalog";
import { headingStyles } from "@/lib/heading";
import { pathFor } from "@/lib/seo";

/**
 * The landing's catalogue teaser: one shelf per catalogue, side by side from
 * `lg` (owner, 2026-11-24, after an app-store style reference). Each shelf is
 * a header — icon, catalogue name, «Все N ›» into /store?cat=<slug> — over two
 * rows of the same square `BrandIcon` as /store, closed by a «+N» tile when
 * more brands are left.
 *
 * Two rows per width: 4 across on a phone (7 brands + the tile), 6 on a
 * tablet where the shelves stack (11 + tile), 5 per shelf side by side from
 * `lg` (9 + tile). Brands past a width's count are hidden there, not dropped,
 * so the order is one list everywhere. Shelves follow the API's category order
 * and only categories with brands show; nothing is keyed to a slug.
 */
const PHONE = 7;
const TABLET = 11;
const DESKTOP = 9;
const SHOWN_MAX = Math.max(PHONE, TABLET, DESKTOP);

function displayFor(index: number): string {
  if (index < PHONE) return "flex";
  if (index < DESKTOP) return "hidden sm:flex";
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

  return (
    <section id="catalog" className="relative scroll-mt-[88px] py-14 sm:py-20">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-10 sm:mb-12">
          <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
            [ 01 / {t("eyebrow")} ]
          </div>
          <h2 className={headingStyles("display", "mt-3")}>
            <span className="block">{t("titleLine1")}</span>
            <span className="text-tx-mute block">{t("titleLine2")}</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-x-10 gap-y-12 lg:grid-cols-2">
          {shelves.map((shelf) => (
            <CatalogShelf key={shelf.category.slug} shelf={shelf} locale={locale} />
          ))}
        </div>
      </div>
    </section>
  );
}

async function CatalogShelf({ shelf, locale }: { shelf: Shelf; locale: string }) {
  const t = await getTranslations("web.catalog");
  const { category, brands, total } = shelf;
  const Icon = (category.icon ? ICONS[category.icon] : undefined) ?? LayoutGrid;
  const href = `${pathFor(locale, "/store")}?cat=${encodeURIComponent(category.slug)}`;
  const headingId = `catalog-${category.slug}`;
  // How many brands the «+N» tile stands for at each width.
  const left = (shown: number): number => total - Math.min(shown, brands.length);

  return (
    <section aria-labelledby={headingId}>
      <div className="mb-5 flex items-center justify-between gap-4">
        <h3 id={headingId} className="flex items-center gap-3">
          <Icon size={26} strokeWidth={2} className="text-primary shrink-0" aria-hidden />
          <span className="font-display text-foreground text-[22px] font-extrabold leading-none tracking-[-0.01em] sm:text-[26px]">
            {category.name}
          </span>
        </h3>
        <Link
          href={href}
          className="text-primary hover:text-foreground focus-visible:ring-primary inline-flex h-10 shrink-0 items-center gap-1 rounded-lg px-1 text-[15px] font-semibold transition focus-visible:outline-none focus-visible:ring-2"
        >
          {t("allCount", { count: total })}
          <ChevronRight size={18} strokeWidth={2.4} aria-hidden />
        </Link>
      </div>

      <div className="grid grid-cols-4 gap-x-3 gap-y-5 sm:grid-cols-6 sm:gap-x-4 lg:grid-cols-5">
        {brands.map((brand, i) => (
          <BrandIcon key={brand.slug} brand={brand} locale={locale} className={displayFor(i)} />
        ))}
        <MoreTile href={href} label={t("seeAll")} left={left} />
      </div>
    </section>
  );
}

/** The last cell: «+N» into the catalogue, per width; gone where nothing is left. */
function MoreTile({
  href,
  label,
  left,
}: {
  href: string;
  label: string;
  left: (shown: number) => number;
}) {
  const phone = left(PHONE);
  const tablet = left(TABLET);
  const desktop = left(DESKTOP);
  if (phone <= 0 && tablet <= 0 && desktop <= 0) return null;
  const display = [
    phone > 0 ? "flex" : "hidden",
    tablet > 0 ? "sm:flex" : "sm:hidden",
    desktop > 0 ? "lg:flex" : "lg:hidden",
  ].join(" ");

  return (
    <Link
      href={href}
      className={`focus-visible:ring-primary focus-visible:ring-offset-bg group min-w-0 flex-col items-center rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-4 ${display}`}
    >
      <span className="bg-muted border-border group-hover:ring-primary/70 text-foreground flex aspect-square w-full items-center justify-center rounded-[22%] border transition group-hover:ring-2">
        <span className="font-display text-[clamp(1.25rem,3.5vw,1.75rem)] font-extrabold leading-none">
          {phone > 0 && <span className="sm:hidden">+{phone}</span>}
          {tablet > 0 && <span className="hidden sm:inline lg:hidden">+{tablet}</span>}
          {desktop > 0 && <span className="hidden lg:inline">+{desktop}</span>}
        </span>
      </span>
      <span className="text-tx-mute group-hover:text-foreground mt-2.5 line-clamp-2 w-full text-center text-[13px] font-semibold leading-tight transition sm:text-sm">
        {label}
      </span>
    </Link>
  );
}
