import { ChevronRight, Clock, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { HighlightChips } from "./HighlightChips";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { RatingSummary } from "@/components/store/RatingSummary";
import { Stars } from "@/components/store/Stars";
import { PurchasePanel } from "@/components/store/PurchasePanel";
import { routing } from "@/i18n/routing";
import { getBrandDetail, getBrandSlugs, getProductDetail, type ProductDetail } from "@/lib/catalog";
import { getBrandReviews, type ReviewPage } from "@/lib/reviews";
import { alternates, formatUzs, GEO_META, localeUrl, ogLocale } from "@/lib/seo";

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
  const description =
    brand.description ?? brand.short_description ?? t("brandMetaDescription", { name: brand.name });
  const path = `/store/${brand.slug}`;
  return {
    title: { absolute: title },
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: { index: true, follow: true },
    openGraph: {
      type: "website",
      siteName: "yupay",
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
  const prefix = `/${locale}`;

  const products = (
    await Promise.all((brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY)))
  ).filter((p): p is ProductDetail => p !== null);

  const about = brand.description ?? brand.short_description ?? "";
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
      }
    : undefined;

  const productLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: brand.name,
    description: about || brand.name,
    image: heroImg ?? undefined,
    brand: { "@type": "Brand", name: brand.name },
    category: brand.category_slug,
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
        <nav className="text-tx-dim mb-7 flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
          <Link href={prefix} className="hover:text-tx-mute transition">
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <Link href={`${prefix}/store`} className="hover:text-tx-mute transition">
            {t("breadcrumbStore")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{brand.name}</span>
        </nav>

        {/* hero banner */}
        <div className="border-border relative overflow-hidden rounded-2xl border">
          {heroImg ? (
            <Image
              src={heroImg}
              alt={brand.name}
              fill
              priority
              unoptimized
              sizes="(max-width: 1024px) 100vw, 1040px"
              className="object-cover object-top"
            />
          ) : (
            <div
              aria-hidden
              className="absolute inset-0"
              style={{
                background: `linear-gradient(135deg, ${brand.accent_color ?? "#AAFF33"}55, #0A0D1A)`,
              }}
            />
          )}
          <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.92)_0%,rgba(0,0,0,0.45)_60%,rgba(0,0,0,0.2)_100%)]" />
          <div className="relative z-10 flex min-h-[300px] flex-col justify-end p-6 sm:min-h-[360px] sm:p-9">
            <div className="flex items-center gap-3">
              {brand.logo_url && (
                <span className="relative h-14 w-14 shrink-0 overflow-hidden rounded-[14px] bg-black/40 backdrop-blur">
                  <Image
                    src={brand.logo_url}
                    alt=""
                    width={56}
                    height={56}
                    unoptimized
                    className="h-full w-full object-cover"
                  />
                </span>
              )}
              {/* Name next to the logo — big and white (the H1). */}
              <h1 className="font-display text-[clamp(2rem,5vw,3.2rem)] font-extrabold leading-[0.98] tracking-[-0.03em] text-white">
                {brand.name}
              </h1>
            </div>
            {/* Short description below the name — smaller and muted. */}
            {brand.short_description && (
              <p className="mt-3 text-[12px] font-bold uppercase leading-relaxed tracking-[0.12em] text-white/70">
                {brand.short_description}
              </p>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-2.5">
              {startingChip && (
                <Chip>
                  {t("from")} {startingChip}
                </Chip>
              )}
              {/* Generic eta/security chips only when the brand has no
                  highlights — otherwise the highlights (e.g. "1–3 минуты",
                  "Без пароля") would duplicate them. */}
              {highlights.length === 0 && (
                <>
                  <Chip icon={<Clock size={13} />}>{t("etaChip", { eta: "1–3" })}</Chip>
                  <Chip icon={<ShieldCheck size={13} />}>{t("securityChip")}</Chip>
                </>
              )}
              <HighlightChips items={highlights} />
              {brand.maintenance && <Chip>{t("maintenance")}</Chip>}
            </div>
          </div>
        </div>

        {about && (
          <div className="mt-10">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("aboutTitle")}</h2>
            <p className="text-tx-mute mt-3 max-w-[680px] text-[15px] leading-relaxed">{about}</p>
          </div>
        )}

        <div className="mt-10">
          {products.length > 0 ? (
            <PurchasePanel products={products} locale={locale} />
          ) : (
            <p className="text-tx-mute">{t("empty")}</p>
          )}
        </div>

        {brand.instructions && (
          <section className="mt-16 scroll-mt-[88px]">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {t("instructionsTitle")}
            </h2>
            <div className="text-tx-mute mt-4 max-w-[760px] whitespace-pre-line text-[15px] leading-relaxed">
              {brand.instructions}
            </div>
          </section>
        )}

        {faqs.length > 0 && (
          <section className="mt-16 scroll-mt-[88px]">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("faqTitle")}</h2>
            <div className="border-border/70 mt-5 max-w-[760px] border-y">
              {faqs.map((f) => (
                <details key={f.id} className="border-border/70 group border-b last:border-b-0">
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

        <section id="reviews" className="mt-16 scroll-mt-[88px]">
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t2("title")}</h2>
          <div className="mt-5 max-w-[760px]">
            <RatingSummary stats={reviews.stats} />
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
