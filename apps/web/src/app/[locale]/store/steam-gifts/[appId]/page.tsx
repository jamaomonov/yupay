import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { DlcBrowser, DlcNote } from "@/components/gifts/DlcBrowser";
import { GiftPurchasePanel } from "@/components/gifts/GiftPurchasePanel";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { getBrandDetail, getProductDetail } from "@/lib/catalog";
import { getGiftDetail, type GiftAppDetail } from "@/lib/gifts";
import { isOptimizable } from "@/lib/image";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS, truncate } from "@/lib/seo";

/** On-demand ISR across ~4 241 app ids — no `generateStaticParams`: the
 *  catalog is too large (and too price-volatile) to prebuild at build time,
 *  same reasoning as the section page's `revalidate`. */
export const revalidate = 300;

/** Same brand/product every game page resolves the purchase SKU through —
 *  the seed script (Task 6) creates exactly one product with one
 *  variable-amount SKU under this brand. */
const GIFT_BRAND_SLUG = "steam-gifts";
const CURRENCY = "UZS";

function path(appId: string): string {
  return `/store/steam-gifts/${appId}`;
}

async function loadDetail(locale: string, appId: string): Promise<GiftAppDetail | null> {
  const id = Number(appId);
  if (!Number.isFinite(id) || !Number.isInteger(id)) return null;
  return getGiftDetail(locale, id);
}

/**
 * The gift SKU id, resolved the same data path every brand page already
 * uses (`getBrandDetail` → `getProductDetail` per product). Returns `null`
 * when the deployed API predates the steam-gifts product/SKU seed (Task 6)
 * or the brand has no product yet — the page still renders, just without a
 * purchase panel (see `GiftPurchasePanel`'s caller below).
 */
async function resolveSkuId(locale: string): Promise<string | null> {
  const brand = await getBrandDetail(GIFT_BRAND_SLUG, locale, CURRENCY);
  const productSummary = brand?.products?.[0];
  if (!productSummary) return null;
  const product = await getProductDetail(productSummary.slug, locale, CURRENCY);
  return product?.skus[0]?.id ?? null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; appId: string }>;
}): Promise<Metadata> {
  const { locale, appId } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const detail = await loadDetail(locale, appId);
  if (!detail) return {};

  const t = await getTranslations("web.gifts.game");
  const title = t("metaTitle", { name: detail.name });
  const description = truncate(t("metaDescription", { name: detail.name }));
  const p = path(appId);
  return {
    title,
    description,
    alternates: alternates(locale, p),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, p),
      images: detail.image ? [{ url: detail.image }] : undefined,
      ...ogLocale(locale),
    },
  };
}

export default async function GiftGamePage({
  params,
}: {
  params: Promise<{ locale: string; appId: string }>;
}) {
  const { locale, appId } = await params;
  setRequestLocale(locale);

  const detail = await loadDetail(locale, appId);
  if (!detail) notFound();

  const skuId = await resolveSkuId(locale);

  const tGifts = await getTranslations("web.gifts");
  const tStore = await getTranslations("web.store");
  const tn = await getTranslations("web.nav");

  const p = path(appId);

  // Product JSON-LD for this one app, priced at the default country's zone
  // — the lowest sell price among its packages there, mirroring how the
  // brand page picks a "starting" chip from several SKUs. `region_default`
  // (2026-09-03) is a country code (e.g. "UZ"), not a zone label, so it's
  // resolved to its zone via `regions` before matching `pkg.prices[].zone`
  // — comparing it to `price.zone` directly (the pre-country-picker
  // behaviour) would silently zero out this Offer for every game page.
  // `regions` is optional (see `GiftAppDetail` in `lib/gifts.ts`): a
  // version-skewed API response that predates this field must simply omit
  // the Offer, not throw and take down the whole page.
  const defaultZone = (detail.regions ?? []).find((r) => r.country === detail.region_default)?.zone;
  const defaultZonePrices = detail.packages
    .flatMap((pkg) => pkg.prices)
    .filter((price) => price.zone === defaultZone)
    .map((price) => (price.price_uzs != null ? Math.round(Number(price.price_uzs)) : null))
    .filter((n): n is number => n !== null);
  const offer =
    defaultZonePrices.length > 0
      ? {
          "@type": "Offer",
          price: Math.min(...defaultZonePrices),
          priceCurrency: CURRENCY,
          availability: "https://schema.org/InStock",
          url: localeUrl(locale, p),
          priceValidUntil: new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10),
        }
      : undefined;

  const productLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: detail.name,
    description: detail.description ?? undefined,
    image: detail.image ?? undefined,
    category: "steam-gifts",
    ...(offer ? { offers: offer } : {}),
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: tStore("breadcrumbHome"), item: localeUrl(locale) },
      {
        "@type": "ListItem",
        position: 2,
        name: tStore("breadcrumbStore"),
        item: localeUrl(locale, "/store"),
      },
      {
        "@type": "ListItem",
        position: 3,
        name: tGifts("hero.title"),
        item: localeUrl(locale, "/store/steam-gifts"),
      },
      { "@type": "ListItem", position: 4, name: detail.name, item: localeUrl(locale, p) },
    ],
  };

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <JsonLd data={productLd} />
      <JsonLd data={breadcrumbLd} />

      <div className="mx-auto max-w-[1100px] px-6 sm:px-10">
        <nav
          aria-label={tn("breadcrumbLabel")}
          className="text-tx-dim mb-6 flex flex-wrap items-center gap-x-1.5 font-mono text-[11px]"
        >
          <Link
            href={pathFor(locale)}
            className="hover:text-tx-mute inline-flex items-center py-2.5 transition"
          >
            {tStore("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <Link
            href={pathFor(locale, "/store/steam-gifts")}
            className="hover:text-tx-mute inline-flex items-center py-2.5 transition"
          >
            {tGifts("hero.title")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{detail.name}</span>
        </nav>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-6">
            <div className="border-border bg-card relative aspect-[16/9] w-full overflow-hidden rounded-xl border">
              {detail.image && (
                <Image
                  src={detail.image}
                  alt={detail.name}
                  fill
                  priority
                  fetchPriority="high"
                  unoptimized={!isOptimizable(detail.image)}
                  sizes="(max-width: 1024px) 100vw, 700px"
                  className="object-cover"
                />
              )}
            </div>

            <h1 className="font-display text-[clamp(1.9rem,3.2vw,2.75rem)] font-bold leading-tight tracking-[-0.025em]">
              {detail.name}
            </h1>

            <DlcNote type={detail.type} />

            {detail.description && (
              <p className="text-tx-mute max-w-[70ch] text-pretty text-[15px] leading-relaxed">
                {detail.description}
              </p>
            )}

            <DlcBrowser appId={detail.app_id} total={detail.dlc_total} locale={locale} />
          </div>

          {/* `max-h`/`overflow-y`: the panel can grow past the viewport
              (a game with several editions, a long country list, a guest
              email field) and, sticky-pinned at a fixed top offset with no
              cap, push its own Buy button below the fold — clipped by the
              viewport but not scrollable within itself (2026-09-04
              review). */}
          <aside className="lg:sticky lg:top-[120px] lg:max-h-[calc(100vh-140px)] lg:self-start lg:overflow-y-auto">
            {skuId ? (
              <GiftPurchasePanel detail={detail} skuId={skuId} locale={locale} />
            ) : (
              <div className="border-border bg-card rounded-2xl border p-6 text-center">
                <p className="text-tx-mute text-sm">{tGifts("comingSoon")}</p>
              </div>
            )}
          </aside>
        </div>
      </div>
    </main>
  );
}
