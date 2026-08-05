import { ChevronRight, Clock, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { HighlightChips } from "./HighlightChips";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { AboutText } from "@/components/store/AboutText";
import { PurchasePanel } from "@/components/store/PurchasePanel";
import { RatingChip } from "@/components/store/RatingChip";
import { RatingSummary } from "@/components/store/RatingSummary";
import { Stars } from "@/components/store/Stars";
import { WriteReviewPanel } from "@/components/store/WriteReviewPanel";
import { routing } from "@/i18n/routing";
import { getBrandDetail, getBrandSlugs, getProductDetail, type ProductDetail } from "@/lib/catalog";
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
} from "@/lib/seo";

const CURRENCY = "UZS";

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
  const brand = await getBrandDetail(brandSlug, locale);
  if (!brand) return {};
  const t = await getTranslations("web.store");
  const title = t("brandMetaTitle", { name: brand.name });
  // short_description first: it's the ~250-char blurb that fits a Google snippet;
  // the long description is truncated. firstNonEmpty skips the API's `""` blanks.
  const description =
    firstNonEmpty(brand.short_description, brand.description) ??
    t("brandMetaDescription", { name: brand.name });
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
      <JsonLd data={breadcrumbLd} />
      {faqLd && <JsonLd data={faqLd} />}

      <div className="mx-auto max-w-[1100px] px-6 sm:px-10">
        <nav className="text-tx-dim mb-6 flex flex-wrap items-center gap-x-1.5 font-mono text-[11px]">
          <Link
            href={pathFor(locale)}
            className="hover:text-tx-mute inline-flex items-center py-1.5 transition"
          >
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <Link
            href={pathFor(locale, "/store")}
            className="hover:text-tx-mute inline-flex items-center py-1.5 transition"
          >
            {t("breadcrumbStore")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{brand.name}</span>
        </nav>

        {/* hero banner — mirrors the design reference: the brand image bleeds
            in from the right while a left-to-right scrim keeps the copy
            readable; content is bottom-aligned over it. */}
        <div className="border-border bg-card relative overflow-hidden rounded-[22px] border">
          {heroImg ? (
            <Image
              src={heroImg}
              alt={brand.name}
              fill
              priority
              unoptimized
              sizes="(max-width: 1024px) 100vw, 1040px"
              className="object-cover"
              style={{ objectPosition: "50% 30%", opacity: 0.6 }}
            />
          ) : (
            <div
              aria-hidden
              className="absolute inset-0"
              style={{
                background: `radial-gradient(120% 120% at 80% 0%, ${brand.accent_color ?? "#AAFF33"}33, transparent 62%)`,
              }}
            />
          )}
          {/* left-to-right scrim (copy side dark, image visible on the right) */}
          <div
            aria-hidden
            className="absolute inset-0"
            style={{
              background:
                "linear-gradient(90deg, hsl(var(--bg)) 0%, hsl(var(--bg)/0.93) 32%, hsl(var(--bg)/0.55) 66%, hsl(var(--bg)/0.18) 100%)",
            }}
          />
          {/* bottom fade so the pills always sit on solid ground */}
          <div
            aria-hidden
            className="absolute inset-0"
            style={{
              background: "linear-gradient(0deg, hsl(var(--bg)) 0%, hsl(var(--bg)/0.05) 58%)",
            }}
          />
          <div className="relative z-10 flex min-h-[272px] flex-col justify-end gap-4 p-6 sm:p-8">
            <div className="flex items-center gap-4">
              {brand.logo_url && (
                <span className="relative h-16 w-16 shrink-0 overflow-hidden rounded-[17px] bg-black/40 shadow-[0_12px_32px_rgba(0,0,0,0.55)] backdrop-blur">
                  <Image
                    src={brand.logo_url}
                    alt=""
                    width={64}
                    height={64}
                    unoptimized
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
              <p className="max-w-[58ch] text-pretty text-[15px] leading-[1.55] text-white/75">
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
              {brand.maintenance && <Chip>{t("maintenance")}</Chip>}
            </div>
          </div>
        </div>

        {/* Pick sits right under the hero; the how-to / about / FAQ sections are
            passed into the left column so the sticky order sidebar scrolls with
            them — one aligned 2-column grid (see PurchasePanel). */}
        <div className="mt-8">
          {products.length > 0 ? (
            <PurchasePanel products={products} locale={locale}>
              {brand.instructions && (
                <section className="mt-14 scroll-mt-[88px]">
                  <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
                    {t("instructionsTitle")}
                  </h2>
                  <div className="text-tx-mute mt-4 whitespace-pre-line text-[15px] leading-relaxed">
                    {brand.instructions}
                  </div>
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

        <section id="reviews" className="mt-16 scroll-mt-[88px]">
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t2("title")}</h2>
          <div className="mt-5 max-w-[760px]">
            <RatingSummary stats={reviews.stats} />
            {/* useSearchParams() inside WriteReviewPanel needs a Suspense
                boundary or `next build`'s static export of this page bails out. */}
            <Suspense fallback={null}>
              <WriteReviewPanel brandSlug={brand.slug} />
            </Suspense>
            {reviews.items.length > 0 && (
              <ul className="mt-8 flex flex-col gap-6">
                {reviews.items.map((r) => (
                  <li key={r.id} className="border-border/70 border-b pb-6 last:border-b-0">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[14px] font-semibold">
                        {r.author_name ?? t2("anonymous")}
                      </span>
                      <Stars value={r.rating} size={13} />
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
