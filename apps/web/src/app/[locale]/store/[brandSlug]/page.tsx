import { AlertTriangle, ChevronRight, Clock, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import type { Metadata } from "next";

import { BrandBlogBlock } from "@/components/blog/BrandBlogBlock";
import { JsonLd } from "@/components/JsonLd";
import { HighlightChips } from "@/components/store/HighlightChips";
import { AboutText } from "@/components/store/AboutText";
import { PurchasePanel } from "@/components/store/PurchasePanel";
import { RatingChip } from "@/components/store/RatingChip";
import { RatingSummary } from "@/components/store/RatingSummary";
import { ReviewAvatar } from "@/components/store/ReviewAvatar";
import { Stars } from "@/components/store/Stars";
import { WriteReviewPanel } from "@/components/store/WriteReviewPanel";
import { routing } from "@/i18n/routing";
import {
  getBrandDetail,
  getBrands,
  getBrandSlugs,
  getProductDetail,
  type ProductDetail,
} from "@/lib/catalog";
import { isOptimizable } from "@/lib/image";
import { regionSibling } from "@/lib/region-sibling";
import { getBrandReviews, type ReviewPage } from "@/lib/reviews";
import {
  alternates,
  firstNonEmpty,
  formatUzs,
  GEO_META,
  localeUrl,
  ogLocale,
  pathFor,
  ROBOTS,
  truncate,
} from "@/lib/seo";

const CURRENCY = "UZS";

/**
 * Declared rather than inherited. Without this the segment takes the *lowest*
 * revalidate of everything it fetches, which was the 60s on `getBrandReviews`
 * — so the landing pages ads point at regenerated five times more often than
 * the 300s this file's own JSON-LD comment assumes, and every regeneration
 * fans out to a brand call plus one per product.
 */
export const revalidate = 300;

export async function generateStaticParams() {
  return (await getBrandSlugs()).map((brandSlug) => ({ brandSlug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}): Promise<Metadata> {
  const { locale, brandSlug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  // Same currency as the page body below. Without it the two calls are
  // different URLs and therefore different Data-Cache keys, so every brand was
  // fetched twice per locale — 108 extra API calls in a build that prerenders
  // 111 store pages, which is what pushed it over the rate limit.
  const brand = await getBrandDetail(brandSlug, locale, CURRENCY);
  if (!brand) return {};
  const t = await getTranslations("web.store");
  const title = t("brandMetaTitle", { name: brand.name });
  // short_description first (skips the API's `""` blanks), trimmed to a clean
  // SERP length — the raw blurbs run ~450 chars and would be cut mid-word.
  const description = truncate(
    firstNonEmpty(brand.short_description, brand.description) ??
      t("brandMetaDescription", { name: brand.name }),
  );
  const path = `/store/${brand.slug}`;
  return {
    title: { absolute: title },
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, path),
      images: brand.hero_image_url ? [{ url: brand.hero_image_url }] : undefined,
      ...ogLocale(locale),
    },
  };
}

export default async function BrandPage({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}) {
  const { locale, brandSlug } = await params;
  setRequestLocale(locale);
  const brand = await getBrandDetail(brandSlug, locale, CURRENCY);
  if (!brand) notFound();

  const t = await getTranslations("web.store");
  const t2 = await getTranslations("web.brandReviews");
  const tn = await getTranslations("web.nav");

  const products = (
    await Promise.all((brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY)))
  ).filter((p): p is ProductDetail => p !== null);

  // Long description first here (the About block has room for it); short as a
  // fallback. firstNonEmpty skips the API's `""` blanks so 6/7 brands stop
  // rendering an empty About / thin Product JSON-LD.
  const about = firstNonEmpty(brand.description, brand.short_description) ?? "";
  const metaDescription =
    firstNonEmpty(brand.short_description, brand.description) ??
    t("brandMetaDescription", { name: brand.name });
  const heroImg = brand.hero_image_url ?? brand.logo_url;
  const highlights = brand.highlights ?? [];
  // The other region's brand, when this one is one half of a `<slug>` /
  // `<slug>-ru` pair (ADR-0079: a brand is one supplier game, so Mobile
  // Legends and Mobile Legends RU are two brands, not one with a toggle).
  const sibling = regionSibling(brand.slug, await getBrands(locale));

  // Reviews are additive: never let a reviews outage break the brand page (or
  // the SSG build prerendering against an API that predates the endpoint).
  const reviews: ReviewPage = await getBrandReviews(brandSlug, locale).catch(() => ({
    items: [],
    next_cursor: null,
    stats: { avg: 0, count: 0, dist: {} },
  }));

  // Starting price chip + JSON-LD offers from real SKU prices.
  const skus = products.flatMap((p) => p.skus);
  const uzs = skus
    .map((s) => (s.display_price ? Math.round(Number(s.display_price.amount)) : null))
    .filter((n): n is number => n !== null);
  const startingChip = uzs.length ? formatUzs(locale, Math.min(...uzs)) : null;

  const offers = uzs.length
    ? {
        "@type": "AggregateOffer",
        priceCurrency: CURRENCY,
        lowPrice: Math.min(...uzs),
        highPrice: Math.max(...uzs),
        offerCount: skus.length,
        availability: "https://schema.org/InStock",
        // Rolling 14-day validity window — safe because this page is ISR
        // revalidate=300, so the date keeps advancing with every regen.
        priceValidUntil: new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10),
      }
    : undefined;

  const productLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: brand.name,
    description: about || metaDescription,
    image: heroImg ?? undefined,
    brand: { "@type": "Brand", name: brand.name },
    category: brand.category_slug,
    // Digital goods: delivery is instant and non-returnable once issued.
    hasMerchantReturnPolicy: {
      "@type": "MerchantReturnPolicy",
      applicableCountry: "UZ",
      returnPolicyCategory: "https://schema.org/MerchantReturnNotPermitted",
    },
    ...(offers ? { offers } : {}),
    ...(reviews.stats.count > 0
      ? {
          aggregateRating: {
            "@type": "AggregateRating",
            ratingValue: reviews.stats.avg,
            reviewCount: reviews.stats.count,
          },
        }
      : {}),
  };
  // Per-SKU Product entries so Google Images can pin a price and stock badge
  // to each SKU image, the way it already does for the brand hero. Fixed-price
  // SKUs only: a variable-amount SKU (Telegram Stars) has a rate, not a price,
  // and a fabricated number here would show wrong money in the SERP.
  const priceValidUntil = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
  const skuProducts = products.flatMap((product) =>
    product.skus
      .filter((sku) => !sku.variable_amount && !sku.min_qty && sku.display_price)
      .map((sku) => ({
        product,
        sku,
        image: sku.image_url ?? product.image_url ?? heroImg,
        price: Math.round(Number(sku.display_price?.amount ?? 0)),
      }))
      .filter((row) => row.image !== null && row.price > 0),
  );
  const skuListLd =
    skuProducts.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "ItemList",
          name: brand.name,
          itemListElement: skuProducts.map((row, i) => ({
            "@type": "ListItem",
            position: i + 1,
            item: {
              "@type": "Product",
              name: `${brand.name} — ${row.sku.denomination ?? row.product.name}`,
              sku: row.sku.sku_code,
              image: row.image,
              brand: { "@type": "Brand", name: brand.name },
              hasMerchantReturnPolicy: {
                "@type": "MerchantReturnPolicy",
                applicableCountry: "UZ",
                returnPolicyCategory: "https://schema.org/MerchantReturnNotPermitted",
              },
              offers: {
                "@type": "Offer",
                price: row.price,
                priceCurrency: CURRENCY,
                availability:
                  (row.sku.in_stock ?? true)
                    ? "https://schema.org/InStock"
                    : "https://schema.org/OutOfStock",
                url: localeUrl(locale, `/store/${brand.slug}`),
                priceValidUntil,
              },
            },
          })),
        }
      : undefined;

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: t("breadcrumbHome"), item: localeUrl(locale) },
      {
        "@type": "ListItem",
        position: 2,
        name: t("breadcrumbStore"),
        item: localeUrl(locale, "/store"),
      },
      {
        "@type": "ListItem",
        position: 3,
        name: brand.name,
        item: localeUrl(locale, `/store/${brand.slug}`),
      },
    ],
  };

  const faqs = brand.faqs ?? [];
  // FAQPage structured data — lets Google show the questions as rich results.
  const faqLd =
    faqs.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqs.map((f) => ({
            "@type": "Question",
            name: f.question,
            acceptedAnswer: { "@type": "Answer", text: f.answer },
          })),
        }
      : undefined;

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <JsonLd data={productLd} />
      {skuListLd && <JsonLd data={skuListLd} />}
      <JsonLd data={breadcrumbLd} />
      {faqLd && <JsonLd data={faqLd} />}

      <div className="mx-auto max-w-[1100px] px-6 sm:px-10">
        <nav
          aria-label={tn("breadcrumbLabel")}
          className="text-tx-dim mb-6 flex flex-wrap items-center gap-x-1.5 font-mono text-[11px]"
        >
          <Link
            href={pathFor(locale)}
            className="hover:text-tx-mute inline-flex items-center py-2.5 transition"
          >
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <Link
            href={pathFor(locale, "/store")}
            className="hover:text-tx-mute inline-flex items-center py-2.5 transition"
          >
            {t("breadcrumbStore")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{brand.name}</span>
        </nav>

        {/* Hero: the art gets a band of its own, the copy sits under it.
            Overlaying the two is what this replaced, and it failed twice. The
            container was ~3.8:1 while every hero in the catalogue is 16:9 (one
            is 4:3), so `object-cover` threw away more than half the frame; and
            on a phone the box turns portrait, where a left-to-right scrim
            keeps nothing readable — the copy simply sat on the artwork.

            The band is 16:9 on a phone, which is the native ratio of most of
            these images, so there the frame is shown whole. From `sm` it goes
            to 2.6:1 — still a crop, but half of what it was, and the subject
            of game key art is centred. Nothing overlaps the copy at any width,
            by construction rather than by tuning a gradient. */}
        <div className="border-border bg-card relative overflow-hidden rounded-xl border">
          {heroImg ? (
            <div className="relative aspect-[16/9] w-full overflow-hidden sm:aspect-[2.6/1]">
              <Image
                src={heroImg}
                alt={brand.name}
                fill
                priority
                // `priority` alone does not raise the request's priority: in Next
                // 15 it only disables lazy loading and emits the preload, and the
                // preload copies `fetchPriority` straight from this prop. Without
                // it the LCP image queues behind the fonts and scripts already in
                // flight — which is exactly what Lighthouse reports here.
                fetchPriority="high"
                unoptimized={!isOptimizable(heroImg)}
                sizes="(max-width: 1024px) 100vw, 1040px"
                className="object-cover"
                // Slightly above centre: game key art puts faces in the upper
                // half, and a centred crop of a 16:9 into 2.6:1 cuts them.
                style={{ objectPosition: "50% 42%" }}
              />
              {/* Only a bottom fade now. The copy is below the image, so this
                  is here to land the band on the card rather than to rescue
                  text from the artwork. */}
              <div
                aria-hidden
                className="absolute inset-0"
                style={{
                  background:
                    "linear-gradient(0deg, hsl(var(--card)) 1%, hsl(var(--card)/0.22) 38%, transparent 72%)",
                }}
              />
            </div>
          ) : (
            /* No hero art. The logo is a square icon and stretching it across
               a 2.6:1 band looks like a mistake, so this gets the accent wash
               and no band at all. */
            <div
              aria-hidden
              className="h-24 w-full sm:h-32"
              style={{
                background: `radial-gradient(120% 140% at 70% 0%, ${brand.accent_color ?? "#AAFF33"}2E, transparent 68%)`,
              }}
            />
          )}
          {/* Pulled up so the logo breaks the band's edge — without it the
              picture and the copy read as two unrelated blocks stacked. */}
          <div className="relative z-10 -mt-7 flex flex-col gap-4 p-6 pt-0 sm:-mt-9 sm:p-8 sm:pt-0">
            <div className="flex items-center gap-4">
              {brand.logo_url && (
                <span className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-black/40 shadow-[0_12px_32px_rgba(0,0,0,0.55)] backdrop-blur">
                  <Image
                    src={brand.logo_url}
                    alt=""
                    width={64}
                    height={64}
                    unoptimized={!isOptimizable(brand.logo_url)}
                    className="h-full w-full object-cover"
                  />
                </span>
              )}
              {/* Name next to the logo — big and white (the H1). */}
              <h1 className="font-display text-[clamp(1.9rem,3.2vw,2.75rem)] font-bold leading-none tracking-[-0.025em] text-white">
                {brand.name}
              </h1>
            </div>
            {/* Short description — normal sentence case, muted, tight measure. */}
            {brand.short_description && (
              <p className="line-clamp-2 max-w-[58ch] text-pretty text-[15px] leading-[1.55] text-white/75 sm:line-clamp-none">
                {brand.short_description}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {startingChip && (
                <span className="border-border-2 inline-flex items-baseline gap-2 rounded-full border bg-black/50 px-3.5 py-2 backdrop-blur">
                  <span className="text-tx-mute text-[12px]">{t("from")}</span>
                  <span className="font-mono text-[14px] font-bold text-white">{startingChip}</span>
                </span>
              )}
              {/* Real rating at the decision point — renders only when there
                  are genuine reviews (count > 0), never fabricated. */}
              <RatingChip stats={reviews.stats} />
              {/* Generic eta/security chips only when the brand has no
                  highlights — otherwise the highlights (e.g. auto-crediting,
                  "Без пароля") would duplicate them. */}
              {highlights.length === 0 && (
                <>
                  <Chip icon={<Clock size={13} />}>{t("etaChip")}</Chip>
                  <Chip icon={<ShieldCheck size={13} />}>{t("securityChip")}</Chip>
                </>
              )}
              <HighlightChips items={highlights} />
              {/* Amber, not the neutral feature-chip treatment it shared with
                  "0% комиссии" — this one means the buyer may reach checkout
                  and fail there. */}
              {brand.maintenance && (
                <span className="inline-flex items-center gap-2 rounded-full border border-amber-400/50 bg-amber-400/10 px-3.5 py-2 text-[12px] font-semibold text-amber-300">
                  <AlertTriangle size={13} aria-hidden />
                  {t("maintenance")}
                </span>
              )}
            </div>
          </div>
        </div>

        {sibling && (
          <p className="border-border/70 mt-6 rounded-md border border-dashed px-4 py-3 text-[14px]">
            <Link
              href={pathFor(locale, `/store/${sibling.slug}`)}
              className="text-primary font-semibold hover:underline"
            >
              {t(brand.slug.endsWith("-ru") ? "regionSiblingGlobal" : "regionSiblingRu", {
                name: sibling.name,
              })}
            </Link>
          </p>
        )}

        {/* Pick sits right under the hero; the how-to / about / FAQ sections are
            passed into the left column so the sticky order sidebar scrolls with
            them — one aligned 2-column grid (see PurchasePanel). */}
        <div className="mt-8">
          {products.length > 0 ? (
            <PurchasePanel
              products={products}
              locale={locale}
              regionSibling={sibling ? { slug: sibling.slug, name: sibling.name } : null}
            >
              {brand.instructions && (
                <section className="mt-14 scroll-mt-[88px]">
                  <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
                    {t("instructionsTitle")}
                  </h2>
                  <div className="text-tx-mute mt-4 whitespace-pre-line text-[15px] leading-relaxed">
                    {brand.instructions}
                  </div>
                  <Link
                    href={pathFor(locale, `/store/${brand.slug}/how-to`)}
                    className="text-primary mt-4 inline-flex items-center gap-1 text-[14px] font-semibold hover:underline"
                  >
                    {t("howToLink")}
                    <ChevronRight size={15} />
                  </Link>
                </section>
              )}
              {about && (
                <section className="mt-14 scroll-mt-[88px]">
                  <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
                    {t("aboutTitle")}
                  </h2>
                  <AboutText text={about} moreLabel={t("readMore")} lessLabel={t("readLess")} />
                </section>
              )}
              {faqs.length > 0 && (
                <section className="mt-14 scroll-mt-[88px]">
                  <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
                    {t("faqTitle")}
                  </h2>
                  <div className="border-border/70 mt-5 border-y">
                    {faqs.map((f) => (
                      <details
                        key={f.id}
                        className="border-border/70 group border-b last:border-b-0"
                      >
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
                          {f.question}
                          <ChevronRight
                            size={16}
                            className="text-tx-dim shrink-0 transition group-open:rotate-90"
                          />
                        </summary>
                        <p className="text-tx-mute -mt-1 pb-4 pr-8 text-[15px] leading-relaxed">
                          {f.answer}
                        </p>
                      </details>
                    ))}
                  </div>
                </section>
              )}
            </PurchasePanel>
          ) : (
            <p className="text-tx-mute">{t("empty")}</p>
          )}
        </div>

        <BrandBlogBlock brandSlug={brand.slug} brandName={brand.name} locale={locale} />

        <section id="reviews" className="mt-16 scroll-mt-[88px]">
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t2("title")}</h2>
          <div className="mt-5 max-w-[760px]">
            <RatingSummary stats={reviews.stats} />
            {/* useSearchParams() inside WriteReviewPanel needs a Suspense
                boundary or `next build`'s static export of this page bails out. */}
            <Suspense fallback={null}>
              <WriteReviewPanel brandSlug={brand.slug} brandName={brand.name} />
            </Suspense>
            {reviews.items.length > 0 && (
              <ul className="mt-8 flex flex-col gap-6">
                {reviews.items.map((r) => (
                  <li key={r.id} className="border-border/70 border-b pb-6 last:border-b-0">
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex min-w-0 items-center gap-2.5">
                        <ReviewAvatar photoUrl={r.author_photo_url} name={r.author_name} />
                        <span className="truncate text-[14px] font-semibold">
                          {r.author_name ?? t2("anonymous")}
                        </span>
                      </span>
                      <Stars
                        value={r.rating}
                        size={13}
                        label={t2("ratingAria", { value: r.rating })}
                      />
                    </div>
                    {r.body && (
                      <p className="text-tx-mute mt-2 whitespace-pre-line text-[14px] leading-relaxed">
                        {r.body}
                      </p>
                    )}
                    <time className="text-tx-dim mt-2 block font-mono text-[11px]">
                      {new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
                        new Date(r.created_at),
                      )}
                    </time>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

function Chip({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-black/40 px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur">
      {icon && <span className="text-primary">{icon}</span>}
      {children}
    </span>
  );
}
