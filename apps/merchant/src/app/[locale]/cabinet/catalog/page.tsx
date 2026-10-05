"use client";

import { LayoutGrid } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import type { BrandSummary } from "@/lib/types";

import { sectionsOf, useCabinet, useSearch } from "@/components/CabinetContext";
import { EmptyState } from "@/components/EmptyState";
import { PageHeading } from "@/components/PageHeading";
import { downloadFile } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/**
 * Cards painted per step. The grid used to mount all 879 brands with 850 lazy
 * images at once, which on a phone was a two-second blank after the data had
 * already arrived; a sentinel near the bottom adds the next step as it comes
 * into view, so scrolling never meets the end and the first paint is cheap.
 */
const PAGE = 48;

/**
 * A tint per brand, stable across renders and sessions.
 *
 * The ground under a logo that does not fill the card, and the whole card for
 * the few brands with no artwork at all. Derived from the slug, so a brand
 * keeps its colour — it reads as identity rather than as decoration.
 */
const TINTS = [
  "from-orange-500/25",
  "from-blue-500/25",
  "from-violet-500/25",
  "from-rose-500/25",
  "from-cyan-500/25",
  "from-lime-500/20",
] as const;

function tintOf(slug: string): string {
  let hash = 0;
  for (const char of slug) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  // `noUncheckedIndexedAccess` types a computed index as possibly undefined
  // even when the modulo makes that impossible; `as const` above is what
  // makes the fallback a known literal rather than a second maybe-undefined.
  return TINTS[hash % TINTS.length] ?? TINTS[0];
}

/**
 * A brand's picture: the game's app icon, square, filling a square.
 *
 * Every logo we hold is a square icon or close to it (the import's covers and
 * the retail brands' key art alike), so the card's picture area is square and
 * the icon fills it edge to edge — the way an app store or fzr's panel shows
 * a game. The earlier 4:3 area either cropped the icon or floated it in a
 * dark field with air around; neither looked like a game tile.
 */
function Logo({ src }: { src: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    /* eslint-disable-next-line @next/next/no-img-element -- the URL is an
       operator-entered absolute one on a host we do not control, so
       `next/image` would need every one of them allowlisted in the config
       and would fail the page on the first that is not. */
    <img
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      onLoad={() => {
        setLoaded(true);
      }}
      className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-200 ${
        loaded ? "opacity-100" : "opacity-0"
      }`}
    />
  );
}

function Card({ brand, locale }: { brand: BrandSummary; locale: string }) {
  const t = useTranslations("merchant.catalog");
  // The cheapest line comes priced from the server; nothing to walk here.
  const from =
    brand.from_usd === null
      ? null
      : { cents: toCents(brand.from_usd), product: brand.from_product ?? "" };
  // The import named most products after their brand, so «PlayStation (US) ·
  // от $1 · PlayStation (US)» said the name twice; the count of lines is the
  // more useful second half there.
  const product =
    from !== null && from.product.toLowerCase() !== brand.name.toLowerCase() ? from.product : null;
  return (
    <Link
      href={pathFor(locale, `/cabinet/catalog/${brand.slug}`)}
      className="border-border bg-card hover:border-border-2 overflow-hidden rounded-xl border transition"
    >
      <div
        className={`bg-card-2 relative aspect-square bg-gradient-to-tr to-transparent ${tintOf(
          brand.slug,
        )}`}
      >
        {brand.logo_url !== null ? (
          <Logo src={brand.logo_url} />
        ) : (
          // No artwork yet: the brand's initial, so a tile is never a bare
          // colour and the grid stays scannable by eye.
          <span
            aria-hidden
            className="font-display text-foreground/30 absolute inset-0 flex items-center justify-center text-5xl font-semibold"
          >
            {brand.name.trim().charAt(0).toUpperCase()}
          </span>
        )}
      </div>
      <div className="px-3 pb-3 pt-2.5">
        <p className="truncate text-[13.5px] font-bold">{brand.name}</p>
        {/* Price first, and only the product name truncates: the price is
            the reason a reseller opens this screen. */}
        <p className="text-tx-dim mt-0.5 flex min-w-0 items-baseline gap-1.5 text-[11.5px]">
          {from === null ? (
            "—"
          ) : (
            <>
              <span className="text-primary-ink shrink-0 font-mono">
                {t("from", { price: `$${formatUsd(from.cents)}` })}
              </span>
              <span className="min-w-0 truncate">
                {product ?? t("skuCount", { count: brand.sku_count })}
              </span>
            </>
          )}
        </p>
      </div>
    </Link>
  );
}

function CatalogGrid() {
  const t = useTranslations("merchant.catalog");
  const tCommon = useTranslations("merchant.common");
  const { locale } = useParams<{ locale: string }>();
  const { catalog } = useCabinet();
  // Deferred: the box lives in the top bar and re-renders this whole grid per
  // keystroke; the cards are cheap to filter but not to paint on every key.
  const query = useDeferredValue(useSearch(t("searchPlaceholder")));
  const section = useSearchParams().get("section");
  const sections = useMemo(() => sectionsOf(catalog), [catalog]);
  const sectionName = sections.find((entry) => entry.slug === section)?.name ?? null;

  const brands = useMemo(() => {
    const all = catalog?.brands ?? [];
    const inSection = section === null ? all : all.filter((b) => b.category_slug === section);
    const needle = query.trim().toLowerCase();
    if (needle === "") return inSection;
    // Brand name or any product under it: a reseller looking for "robux"
    // is looking for Roblox, and typing the currency is the natural way in.
    return inSection.filter(
      (brand) =>
        brand.name.toLowerCase().includes(needle) ||
        brand.product_names.some((name) => name.toLowerCase().includes(needle)),
    );
  }, [catalog, section, query]);

  const [shown, setShown] = useState(PAGE);
  useEffect(() => {
    setShown(PAGE);
  }, [section, query]);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (node === null || shown >= brands.length) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setShown((n) => n + PAGE);
      },
      { rootMargin: "600px" },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [shown, brands.length]);

  const sectionHref = (slug: string | null) =>
    slug === null
      ? pathFor(locale, "/cabinet/catalog")
      : pathFor(locale, `/cabinet/catalog?section=${slug}`);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeading icon={LayoutGrid} title={sectionName ?? t("title")} />
        <button
          type="button"
          onClick={() => {
            void downloadFile("/catalog.csv").catch(() => undefined);
          }}
          className="border-border bg-card rounded-btn text-tx-mute border px-3 py-1.5 text-xs font-semibold"
        >
          {tCommon("exportCsv")}
        </button>
      </div>

      {/* The sidebar lists the sections on desktop; below `md` it is gone,
          and a reseller on a phone had no way to see gift cards apart from
          top-ups short of typing. */}
      {sections.length > 0 && (
        <div className="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 md:hidden">
          {[null, ...sections.map((s) => s.slug)].map((slug) => {
            const active = slug === section;
            const label =
              slug === null
                ? t("sectionAll")
                : (sections.find((s) => s.slug === slug)?.name ?? slug);
            return (
              <Link
                key={slug ?? "all"}
                href={sectionHref(slug)}
                aria-current={active ? "page" : undefined}
                className={`rounded-btn shrink-0 border px-3 py-1.5 text-xs ${
                  active
                    ? "border-primary bg-primary text-primary-foreground font-semibold"
                    : "border-border text-tx-mute"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>
      )}

      {catalog === null && (
        <div
          aria-busy
          className="mt-5 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
        >
          {Array.from({ length: 10 }, (_, i) => (
            <div key={i} className="border-border bg-card animate-pulse rounded-xl border">
              <div className="bg-card-2 aspect-square" />
              <div className="space-y-2 px-3 pb-3 pt-2.5">
                <div className="bg-card-2 h-3.5 w-2/3 rounded" />
                <div className="bg-card-2 h-3 w-1/2 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {catalog !== null && brands.length === 0 && (
        <EmptyState icon={LayoutGrid} title={t("empty")} />
      )}

      <div className="mt-5 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {brands.slice(0, shown).map((brand) => (
          <Card key={brand.brand_id} brand={brand} locale={locale} />
        ))}
      </div>

      {shown < brands.length && (
        <div ref={sentinel} className="mt-5 flex justify-center">
          <button
            type="button"
            onClick={() => {
              setShown((n) => n + PAGE);
            }}
            className="border-border rounded-btn border px-4 py-2 text-sm font-semibold"
          >
            {t("showMore")}
          </button>
        </div>
      )}
    </div>
  );
}

export default function CatalogPage() {
  return (
    <Suspense fallback={null}>
      <CatalogGrid />
    </Suspense>
  );
}
