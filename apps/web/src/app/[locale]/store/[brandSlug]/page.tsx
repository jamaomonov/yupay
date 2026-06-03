import { ChevronRight, Clock, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { PurchasePanel } from "@/components/store/PurchasePanel";
import { routing } from "@/i18n/routing";
import { getBrandDetail, getBrandSlugs, getProductDetail, type ProductDetail } from "@/lib/catalog";
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
  const prefix = `/${locale}`;

  const products = (
    await Promise.all(brand.products.map((p) => getProductDetail(p.slug, locale, CURRENCY)))
  ).filter((p): p is ProductDetail => p !== null);

  const about = brand.description ?? brand.short_description ?? "";
  const heroImg = brand.hero_image_url ?? brand.logo_url;

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

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <JsonLd data={productLd} />
      <JsonLd data={breadcrumbLd} />

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
              className="object-cover"
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
          <div className="relative z-10 flex min-h-[260px] flex-col justify-end p-6 sm:min-h-[300px] sm:p-9">
            <div className="flex items-center gap-3">
              {brand.logo_url && (
                <span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-[13px] border border-white/15 bg-black/40 backdrop-blur">
                  <Image
                    src={brand.logo_url}
                    alt=""
                    width={32}
                    height={32}
                    unoptimized
                    className="h-8 w-8 object-contain"
                  />
                </span>
              )}
              {brand.short_description && (
                <div className="text-[12px] font-bold uppercase tracking-[0.12em] text-white/70">
                  {brand.short_description}
                </div>
              )}
            </div>
            <h1 className="font-display mt-3 text-[clamp(2rem,5vw,3.2rem)] font-extrabold leading-[0.98] tracking-[-0.03em] text-white">
              {brand.name}
            </h1>
            <div className="mt-4 flex flex-wrap items-center gap-2.5">
              {startingChip && (
                <Chip>
                  {t("from")} {startingChip}
                </Chip>
              )}
              <Chip icon={<Clock size={13} />}>{t("etaChip", { eta: "1–3" })}</Chip>
              <Chip icon={<ShieldCheck size={13} />}>{t("securityChip")}</Chip>
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
