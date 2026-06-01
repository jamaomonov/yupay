import { ArrowUpRight, ChevronRight, Clock, Percent, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { brandSlugs, getBrand, type Pack } from "@/lib/catalog";
import { alternates, formatUzs, GEO_META, localeUrl, ogLocale, SITE } from "@/lib/seo";

export function generateStaticParams() {
  return brandSlugs().map((brandSlug) => ({ brandSlug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}): Promise<Metadata> {
  const { locale, brandSlug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const brand = getBrand(brandSlug);
  if (!brand) return {};
  const t = await getTranslations("web.store");
  const title = t("brandMetaTitle", { name: brand.name });
  const description = t("brandMetaDescription", { name: brand.name });
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
      images: [{ url: `${SITE}${brand.art}` }],
      ...ogLocale(locale),
    },
  };
}

function packLabel(pack: Pack, monthsUnit: string): string {
  if (pack.months) return `${String(pack.months)} ${monthsUnit}`;
  return pack.label ?? "";
}

export default async function BrandPage({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}) {
  const { locale, brandSlug } = await params;
  setRequestLocale(locale);
  const brand = getBrand(brandSlug);
  if (!brand) notFound();

  const t = await getTranslations("web.store");
  const tc = await getTranslations("web.catalog");
  const tShow = await getTranslations("web.showcase");
  const prefix = `/${locale}`;
  const monthsUnit = t("monthsShort");
  const prices = brand.packs.map((p) => p.priceUzs);
  const about = t(`brands.${brand.slug}.about`);

  const productLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: brand.name,
    description: about,
    image: `${SITE}${brand.art}`,
    brand: { "@type": "Brand", name: brand.name },
    category: brand.category,
    offers: {
      "@type": "AggregateOffer",
      priceCurrency: "UZS",
      lowPrice: Math.min(...prices),
      highPrice: Math.max(...prices),
      offerCount: brand.packs.length,
      availability: "https://schema.org/InStock",
      url: localeUrl(locale, `/store/${brand.slug}`),
    },
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
        {/* breadcrumb */}
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
        <div className="border-border relative overflow-hidden rounded-[24px] border">
          <Image
            src={brand.art}
            alt={brand.name}
            fill
            priority
            sizes="(max-width: 1024px) 100vw, 1040px"
            className="object-cover"
          />
          <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.92)_0%,rgba(0,0,0,0.45)_60%,rgba(0,0,0,0.2)_100%)]" />
          <div className="relative z-10 flex min-h-[260px] flex-col justify-end p-6 sm:min-h-[300px] sm:p-9">
            <div className="flex items-center gap-3">
              {brand.icon && (
                <span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-[13px] border border-white/15 bg-black/40 backdrop-blur">
                  <Image
                    src={brand.icon}
                    alt=""
                    width={32}
                    height={32}
                    className="h-8 w-8 object-contain"
                  />
                </span>
              )}
              <div className="text-[12px] font-bold uppercase tracking-[0.12em] text-white/70">
                {tc(`cards.${brand.slug}.eyebrow`)}
              </div>
            </div>
            <h1 className="font-display mt-3 text-[clamp(2rem,5vw,3.2rem)] font-extrabold leading-[0.98] tracking-[-0.03em] text-white">
              {brand.name}
            </h1>
            <div className="mt-4 flex flex-wrap items-center gap-2.5">
              <Chip icon={<Percent size={13} />}>
                {t("commissionChip", { pct: brand.commissionFrom })}
              </Chip>
              <Chip icon={<Clock size={13} />}>{t("etaChip", { eta: brand.etaMinutes })}</Chip>
              <Chip icon={<ShieldCheck size={13} />}>{t("securityChip")}</Chip>
            </div>
          </div>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-10 lg:grid-cols-[1.4fr_1fr]">
          {/* left: about + packs */}
          <div>
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("aboutTitle")}</h2>
            <p className="text-tx-mute mt-3 max-w-[560px] text-[15px] leading-relaxed">{about}</p>

            <h2 className="font-display mt-10 text-xl font-bold tracking-[-0.02em]">
              {t("packsTitle")}
            </h2>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-2">
              {brand.packs.map((pack) => (
                <div
                  key={pack.id}
                  className="border-border bg-card hover:border-primary/40 flex flex-col gap-2 rounded-[16px] border p-4 transition"
                >
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-display text-lg font-bold tracking-[-0.01em]">
                      {packLabel(pack, monthsUnit)}
                    </span>
                    {pack.bonus && (
                      <span className="text-primary text-[12px] font-bold">{pack.bonus}</span>
                    )}
                  </div>
                  <span className="text-tx-mute font-mono text-[13px]">
                    {formatUzs(locale, pack.priceUzs)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* right: CTA card */}
          <aside className="lg:sticky lg:top-[100px] lg:self-start">
            <div className="border-border rounded-[20px] border bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--bg)))] p-6">
              <h2 className="font-display text-lg font-bold tracking-[-0.02em]">{t("payTitle")}</h2>
              <p className="text-tx-mute mt-2 text-[14px] leading-relaxed">{t("ctaNote")}</p>

              <a
                href="https://t.me/yupay_bot"
                target="_blank"
                rel="noreferrer noopener"
                className="bg-primary text-primary-foreground mt-5 flex h-[52px] items-center justify-center gap-2 rounded-[12px] text-[15px] font-bold shadow-[0_12px_30px_-10px_hsl(var(--primary)/0.45)] transition hover:-translate-y-0.5"
              >
                {tShow("cta")}
                <ArrowUpRight size={17} strokeWidth={2.6} />
              </a>

              <div className="border-border/70 text-tx-mute mt-5 flex items-start gap-2.5 border-t pt-5 text-[13px] leading-relaxed">
                <ShieldCheck size={16} className="text-primary mt-0.5 shrink-0" />
                {t("securityNote")}
              </div>
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}

function Chip({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-black/40 px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur">
      <span className="text-primary">{icon}</span>
      {children}
    </span>
  );
}
