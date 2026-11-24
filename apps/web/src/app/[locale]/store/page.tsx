import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { TrustBand } from "@/components/sections/TrustBand";
import { BrandIcon } from "@/components/store/BrandIcon";
import { StoreFilter } from "@/components/store/StoreFilter";
import { routing } from "@/i18n/routing";
import { brandPath } from "@/lib/brand-href";
import { byPopularity } from "@/lib/brand-order";
import { getBrands, getCategories, type BrandSummary, type CategoryOut } from "@/lib/catalog";
import { chipStyles } from "@/lib/chip";
import { headingStyles } from "@/lib/heading";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";

export const revalidate = 300;

const PAY = [
  { src: "/payment/click-dark.svg", name: "Click", w: 157, h: 40 },
  { src: "/payment/payme.png", name: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", name: "Uzum", w: 506, h: 148 },
  { src: "/payment/paynet.svg", name: "Paynet", w: 182, h: 42 },
];

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.store");
  const title = t("meta.title");
  const description = t("meta.description");
  return {
    title,
    description,
    alternates: alternates(locale, "/store"),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, "/store"),
      ...ogLocale(locale),
    },
  };
}

export default async function StorePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("web.store");
  const tn = await getTranslations("web.nav");

  // Fetch the whole catalog once and hand every tile to `StoreFilter`, which
  // picks the visible ones from `?cat=`. Reading that here instead opts the
  // route into dynamic rendering — which is what silently disabled the
  // `revalidate` above and put an origin render behind every visitor.
  let allBrands: BrandSummary[] = [];
  let categories: CategoryOut[] = [];
  try {
    [categories, allBrands] = await Promise.all([getCategories(locale), getBrands(locale)]);
  } catch {
    // API unreachable → render an empty catalog rather than a 500.
  }

  const catName = new Map(categories.map((c) => [c.slug, c.name]));
  const present: string[] = [];
  for (const b of allBrands) {
    if (!present.includes(b.category_slug)) present.push(b.category_slug);
  }
  const chips = [
    { slug: "all", label: t("filterAll") },
    ...present.map((slug) => ({ slug, label: catName.get(slug) ?? slug })),
  ];

  const collectionLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: t("meta.title"),
    description: t("meta.description"),
    url: localeUrl(locale, "/store"),
    inLanguage: locale,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: allBrands.map((b, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: localeUrl(locale, brandPath(b.slug)),
        name: b.name,
      })),
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
    ],
  };

  // Pillar content: a generic "how it works" + a cross-brand FAQ (with schema)
  // turn the catalog into the topical hub the brand/guide pages hang off.
  const steps = [1, 2, 3].map((n) => ({
    t: t(`hubStep${String(n)}T`),
    d: t(`hubStep${String(n)}D`),
  }));
  const hubFaqs = [1, 2, 3, 4, 5, 6].map((n) => ({
    q: t(`hubFaqQ${String(n)}`),
    a: t(`hubFaqA${String(n)}`),
  }));
  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: hubFaqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };

  return (
    <main className="relative min-h-screen pb-28 pt-[96px] sm:pt-[104px]">
      <JsonLd data={collectionLd} />
      <JsonLd data={breadcrumbLd} />
      <JsonLd data={faqLd} />

      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <nav
          aria-label={tn("breadcrumbLabel")}
          className="text-tx-dim mb-4 flex items-center gap-1.5 text-xs"
        >
          <Link href={pathFor(locale)} className="hover:text-tx-mute transition">
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{t("breadcrumbStore")}</span>
        </nav>

        {/* Compact on purpose: the catalogue is the page, the header only
            names it (owner, 2026-11-24 — the old hero pushed every game below
            the fold). */}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between lg:gap-10">
          <div className="max-w-[680px]">
            <h1 className="font-display text-[clamp(1.6rem,3.4vw,2.4rem)] font-extrabold leading-[1.05] tracking-[-0.03em]">
              {t("title")}
            </h1>
            <p className="text-tx-mute mt-2 line-clamp-2 text-sm leading-relaxed sm:line-clamp-none sm:text-[15px]">
              {t("subtitle")}
            </p>
          </div>
          <div role="group" className="flex shrink-0 items-center gap-2" aria-label={t("payWith")}>
            {PAY.map((p) => (
              <span
                key={p.name}
                className="flex h-8 w-12 items-center justify-center rounded-md bg-white p-1"
              >
                <Image
                  src={p.src}
                  alt={p.name}
                  title={p.name}
                  width={p.w}
                  height={p.h}
                  style={{ maxWidth: "100%", maxHeight: "100%", width: "auto", height: "auto" }}
                  className="object-contain"
                />
              </span>
            ))}
          </div>
        </div>

        <StoreFilter
          locale={locale}
          chips={chips}
          emptyLabel={t("empty")}
          searchLabel={t("searchLabel")}
          items={byPopularity(allBrands).map((brand) => ({
            key: brand.slug,
            category: brand.category_slug,
            name: brand.name,
            // The key lives on the tile itself: `StoreFilter` renders it as the
            // direct grid child.
            node: <BrandIcon key={brand.slug} brand={brand} locale={locale} />,
          }))}
        />

        {/* How it works */}
        <section className="mt-20">
          <h2 className={headingStyles("section")}>{t("hubHowTitle")}</h2>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {steps.map((s, i) => (
              <div key={i} className="border-border bg-card rounded-lg border p-6">
                <div className="bg-primary/10 text-primary flex h-9 w-9 items-center justify-center rounded-full font-mono text-[14px] font-bold">
                  {i + 1}
                </div>
                <div className="font-display mt-4 text-lg font-bold">{s.t}</div>
                <p className="text-tx-mute mt-2 text-[14px] leading-relaxed">{s.d}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Per-brand guide links — feeds the how-to pages internal link equity */}
        {allBrands.length > 0 && (
          <section className="mt-14">
            <h2 className={headingStyles("section")}>{t("hubGuidesTitle")}</h2>
            <div className="mt-6 flex flex-wrap gap-3">
              {allBrands.map((b) => (
                <Link
                  key={b.slug}
                  href={pathFor(locale, `/store/${b.slug}/how-to`)}
                  className={chipStyles()}
                >
                  {t("hubGuideLink", { name: b.name })}
                  <ChevronRight size={14} />
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Cross-brand FAQ (matches the FAQPage schema above) */}
        <section className="mt-14">
          <h2 className={headingStyles("section")}>{t("hubFaqTitle")}</h2>
          <div className="border-border/70 mt-6 max-w-[820px] border-y">
            {hubFaqs.map((f, i) => (
              <details key={i} className="border-border/70 group border-b last:border-b-0">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
                  {f.q}
                  <ChevronRight
                    size={16}
                    className="text-tx-dim shrink-0 transition group-open:rotate-90"
                  />
                </summary>
                <p className="text-tx-mute -mt-1 pb-4 pr-8 text-[15px] leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </section>
      </div>

      <div className="mt-16">
        <TrustBand />
      </div>
    </main>
  );
}
