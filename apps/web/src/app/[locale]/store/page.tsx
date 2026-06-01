import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { BrandCard } from "@/components/store/BrandCard";
import { routing } from "@/i18n/routing";
import { BRANDS, CATEGORIES, brandsByCategory } from "@/lib/catalog";
import { alternates, GEO_META, localeUrl, ogLocale } from "@/lib/seo";

const PAY = [
  { src: "/payment/click.png", name: "Click", w: 225, h: 225 },
  { src: "/payment/payme.png", name: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", name: "Uzum", w: 506, h: 148 },
  { src: "/payment/usdt.png", name: "USDT", w: 2000, h: 2000 },
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
    robots: { index: true, follow: true },
    openGraph: {
      type: "website",
      siteName: "yupay",
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
  const prefix = `/${locale}`;
  const active = cat && (CATEGORIES as string[]).includes(cat) ? cat : "all";
  const brands = brandsByCategory(active);

  const filters = [
    { key: "all", label: t("filterAll") },
    { key: "games", label: t("filterGames") },
    { key: "wallets", label: t("filterWallets") },
    { key: "subscriptions", label: t("filterSubscriptions") },
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
      itemListElement: BRANDS.map((b, i) => ({
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

      {/* atmosphere */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px]">
        <div className="grid-cell absolute inset-0" />
        <div
          className="glow-lime absolute"
          style={{ width: 600, height: 600, right: "6%", top: "-14%" }}
        />
      </div>

      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        {/* breadcrumb */}
        <nav className="text-tx-dim mb-7 flex items-center gap-1.5 font-mono text-[11px]">
          <Link href={prefix} className="hover:text-tx-mute transition">
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

        {/* UZ payment strip */}
        <div className="mt-7 flex flex-wrap items-center gap-2.5">
          <span className="text-tx-dim font-mono text-[11px] uppercase tracking-[0.12em]">
            {t("payWith")}
          </span>
          {PAY.map((p) => (
            <span key={p.name} className="flex h-7 items-center rounded-md bg-white px-2">
              <Image
                src={p.src}
                alt={p.name}
                width={p.w}
                height={p.h}
                style={{ width: "auto", height: 16 }}
                className="object-contain"
              />
            </span>
          ))}
          <span className="text-tx-mute flex h-7 items-center rounded-md bg-white px-2 text-[11px] font-bold text-black">
            СБП
          </span>
        </div>

        {/* filters */}
        <div className="mt-10 flex flex-wrap gap-2.5">
          {filters.map((f) => {
            const isActive = f.key === active;
            const href = f.key === "all" ? `${prefix}/store` : `${prefix}/store?cat=${f.key}`;
            return (
              <Link
                key={f.key}
                href={href}
                className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
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

        {/* grid */}
        <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {brands.map((brand) => (
            <BrandCard key={brand.slug} brand={brand} locale={locale} />
          ))}
        </div>
      </div>
    </main>
  );
}
