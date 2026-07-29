import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { TrustBand } from "@/components/sections/TrustBand";
import { BrandCard } from "@/components/store/BrandCard";
import { routing } from "@/i18n/routing";
import { getBrands, getCategories, type BrandSummary, type CategoryOut } from "@/lib/catalog";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";

export const revalidate = 300;

const PAY = [
  { src: "/payment/click-dark.svg", name: "Click", w: 157, h: 40 },
  { src: "/payment/payme.png", name: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", name: "Uzum", w: 506, h: 148 },
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

export default async function StorePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ cat?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const { cat } = await searchParams;
  const t = await getTranslations("web.store");

  // Fetch the whole catalog once; filter in-render by the ?cat= segment so the
  // page stays server-rendered per URL without an extra round-trip.
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
  const active = cat && present.includes(cat) ? cat : "all";
  const brands = active === "all" ? allBrands : allBrands.filter((b) => b.category_slug === active);

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
        url: localeUrl(locale, `/store/${b.slug}`),
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

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <JsonLd data={collectionLd} />
      <JsonLd data={breadcrumbLd} />

      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px]">
        <div className="grid-cell absolute inset-0" />
        <div
          className="glow-lime absolute"
          style={{ width: 600, height: 600, right: "6%", top: "-14%" }}
        />
      </div>

      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <nav className="text-tx-dim mb-7 flex items-center gap-1.5 font-mono text-[11px]">
          <Link href={pathFor(locale)} className="hover:text-tx-mute transition">
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{t("breadcrumbStore")}</span>
        </nav>

        <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
          [ {t("eyebrow")} ]
        </div>
        <h1 className="font-display mt-3 max-w-[760px] text-[clamp(2.2rem,5vw,3.6rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
          {t("title")}
        </h1>
        <p className="text-tx-mute mt-5 max-w-[620px] text-base leading-relaxed sm:text-lg">
          {t("subtitle")}
        </p>

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <span className="text-tx-dim font-mono text-[11px] uppercase tracking-[0.12em]">
            {t("payWith")}
          </span>
          {PAY.map((p) => (
            <span
              key={p.name}
              className="flex h-11 w-16 items-center justify-center rounded-lg bg-white p-1.5"
            >
              <Image
                src={p.src}
                alt={p.name}
                title={p.name}
                width={p.w}
                height={p.h}
                unoptimized
                style={{ maxWidth: "100%", maxHeight: "100%", width: "auto", height: "auto" }}
                className="object-contain"
              />
            </span>
          ))}
        </div>

        {chips.length > 1 && (
          <div className="mt-10 flex flex-wrap gap-2.5">
            {chips.map((f) => {
              const isActive = f.slug === active;
              const href =
                f.slug === "all"
                  ? pathFor(locale, "/store")
                  : pathFor(locale, `/store?cat=${f.slug}`);
              return (
                <Link
                  key={f.slug}
                  href={href}
                  aria-current={isActive ? "page" : undefined}
                  className={`inline-flex h-11 items-center rounded-full border px-4 text-sm font-semibold transition ${
                    isActive
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-muted text-tx-mute hover:text-foreground"
                  }`}
                >
                  {f.label}
                </Link>
              );
            })}
          </div>
        )}

        {brands.length > 0 ? (
          <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {brands.map((brand) => (
              <BrandCard key={brand.slug} brand={brand} locale={locale} />
            ))}
          </div>
        ) : (
          <p className="text-tx-mute mt-10 text-base">{t("empty")}</p>
        )}
      </div>

      <div className="mt-16">
        <TrustBand />
      </div>
    </main>
  );
}
