import { hasWear, isVanilla } from "@yupay/utils";
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
import { SkinOffersProvider } from "@/components/skins/SkinOffers";
import { SkinWearPicker } from "@/components/skins/SkinWearPicker";
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

  const name = isVanilla(item) ? t("vanilla") : (item.skin ?? item.name);
  const category = t(`category.${item.category as SkinCategory}`); // one of SKIN_CATEGORIES
  const floatRange =
    item.min_float !== null && item.max_float !== null
      ? `${Number(item.min_float).toFixed(2)}–${Number(item.max_float).toFixed(2)}`
      : null;
  const worn = hasWear(item.category);

  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6">
      <nav className="text-tx-dim mb-4 flex flex-wrap items-center gap-1 text-[13px]">
        <Link href={pathFor(locale, "/skins")} className="hover:text-foreground">
          {t("market")}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" />
        <Link href={categoryHref} className="hover:text-foreground">
          {item.weapon ?? category}
        </Link>
      </nav>

      <SkinOffersProvider slug={item.slug}>
        <section className="border-border bg-card grid gap-6 rounded-2xl border p-5 md:grid-cols-2 md:p-8">
          <div
            className="bg-muted relative aspect-[4/3] overflow-hidden rounded-xl border-b-[3px] border-transparent md:max-h-[380px]"
            style={item.rarity_color ? { borderBottomColor: item.rarity_color } : undefined}
          >
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
          <div className="flex flex-col gap-5">
            <div>
              <p className="text-tx-dim text-[14px] font-semibold">
                {item.stattrak && <span className="text-orange-400">StatTrak™ </span>}
                {item.souvenir && <span className="text-yellow-400">Souvenir </span>}
                {item.weapon ?? category}
              </p>
              <h1 className="font-display text-2xl font-bold md:text-3xl">
                {name}
                {item.phase && <span className="text-tx-mute"> · {item.phase}</span>}
              </h1>
            </div>
            <SkinPriceBlock
              storedUzs={item.price_uzs}
              storedUsd={item.price_usd}
              steamUrl={steamMarketUrl(item.name)}
              locale={locale}
            />
            {worn && item.family.length > 1 && (
              <SkinWearPicker family={item.family} current={item} locale={locale} />
            )}
            <dl className="border-border grid grid-cols-2 gap-x-6 gap-y-2 border-t pt-4 text-[13px] sm:grid-cols-3">
              {item.exterior && <Fact label={t("wear")} value={t(`exterior.${item.exterior}`)} />}
              {item.rarity && (
                <Fact
                  label={t("rarity")}
                  value={item.rarity}
                  {...(item.rarity_color ? { color: item.rarity_color } : {})}
                />
              )}
              {worn && floatRange && <Fact label={t("float")} value={floatRange} />}
              {!worn && item.count > 0 && (
                <Fact label={t("inStock")} value={t("pieces", { count: item.count })} />
              )}
            </dl>
          </div>
        </section>

        {worn && (
          <section className="mt-8">
            <h2 className="mb-3 text-[17px] font-bold">
              {t("offers")}{" "}
              <span className="text-tx-dim text-[14px] tabular-nums">{item.count}</span>
            </h2>
            <SkinListings locale={locale} />
          </section>
        )}
      </SkinOffersProvider>
    </main>
  );
}

function Fact({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <dt className="text-tx-dim text-[12px]">{label}</dt>
      <dd className="font-semibold" style={color ? { color } : undefined}>
        {value}
      </dd>
    </div>
  );
}
