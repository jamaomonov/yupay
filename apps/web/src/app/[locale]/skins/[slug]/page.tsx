import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { SkinCategory } from "@/lib/skins";
import type { Metadata } from "next";

import { SkinListings } from "@/components/skins/SkinListings";
import { SkinPriceBlock } from "@/components/skins/SkinPriceBlock";
import { SkinWearTiles } from "@/components/skins/SkinWearTiles";
import { routing } from "@/i18n/routing";
import { isOptimizable } from "@/lib/image";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";
import { steamImageSize } from "@/lib/skin-float";
import { DEFAULT_SORT, displayPrice, getSkinDetail, skinQueryString } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; slug: string }>;
}

const steamMarketUrl = (name: string) =>
  `https://steamcommunity.com/market/listings/730/${encodeURIComponent(name)}`;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const item = await getSkinDetail(locale, slug);
  if (item === null) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const name = item.phase ? `${item.name} ${item.phase}` : item.name;
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const title = t("meta.itemTitle", { name });
  // No price, no "от —": the description drops the price rather than print a hole.
  const description =
    price !== null
      ? t("meta.itemDescription", { name, price })
      : t("meta.itemDescriptionNoPrice", { name });
  const path = `/skins/${slug}`;
  return {
    title,
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
      ...(item.image_url ? { images: [steamImageSize(item.image_url, "512fx384f")] } : {}),
      ...ogLocale(locale),
    },
  };
}

export default async function SkinPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const item = await getSkinDetail(locale, slug);
  if (item === null) notFound();
  const t = await getTranslations("web.skins");
  const categoryHref =
    pathFor(locale, "/skins") +
    skinQueryString(
      { sort: DEFAULT_SORT },
      item.weapon ? { category: item.category as SkinCategory, weapon: item.weapon } : {},
    ); // category comes from our own API, one of SKIN_CATEGORIES

  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6">
      <nav className="text-tx-dim mb-4 flex flex-wrap items-center gap-1 text-[13px]">
        <Link href={pathFor(locale, "/skins")} className="hover:text-foreground">
          {t("market")}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" />
        <Link href={categoryHref} className="hover:text-foreground">
          {item.weapon ?? item.category}
        </Link>
      </nav>

      <section className="border-border bg-card grid gap-6 rounded-2xl border p-5 md:grid-cols-2 md:p-8">
        <div className="bg-muted relative aspect-[4/3] overflow-hidden rounded-xl">
          {item.image_url && (
            <Image
              src={steamImageSize(item.image_url, "512fx384f")}
              alt={item.name}
              fill
              priority
              unoptimized={!isOptimizable(item.image_url)}
              sizes="(min-width: 768px) 50vw, 100vw"
              className="object-contain p-6"
            />
          )}
        </div>
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-tx-dim text-[14px] font-semibold">
              {item.stattrak && <span className="text-orange-400">StatTrak™ </span>}
              {item.souvenir && <span className="text-yellow-400">Souvenir </span>}
              {item.weapon}
            </p>
            <h1 className="font-display text-2xl font-bold md:text-3xl">
              {item.skin ?? item.name}
              {item.phase && <span className="text-tx-mute"> · {item.phase}</span>}
            </h1>
            <p className="text-tx-mute mt-1 text-[14px]">
              {item.exterior && t(`exterior.${item.exterior}`)}
              {item.rarity && (
                <span style={item.rarity_color ? { color: item.rarity_color } : undefined}>
                  {item.exterior ? " · " : ""}
                  {item.rarity}
                </span>
              )}
            </p>
          </div>
          <SkinPriceBlock
            priceUzs={item.price_uzs}
            priceUsd={item.price_usd}
            steamUrl={steamMarketUrl(item.name)}
            locale={locale}
          />
        </div>
      </section>

      {item.family.length > 1 && (
        <section className="mt-8">
          <h2 className="mb-3 text-[17px] font-bold">{t("otherWears")}</h2>
          <SkinWearTiles family={item.family} current={item.slug} locale={locale} />
        </section>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-[17px] font-bold">
          {t("offers")} <span className="text-tx-dim font-mono text-[14px]">{item.count}</span>
        </h2>
        <SkinListings slug={item.slug} locale={locale} />
      </section>
    </main>
  );
}
