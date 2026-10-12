import { hasWear, isVanilla } from "@yupay/utils";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { SkinCategory } from "@/lib/skins";
import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { SkinBuyPanel } from "@/components/skins/SkinBuyPanel";
import { SkinFaq } from "@/components/skins/SkinFaq";
import { SkinHero } from "@/components/skins/SkinHero";
import { SkinHowItWorks } from "@/components/skins/SkinHowItWorks";
import { SkinListings } from "@/components/skins/SkinListings";
import { SkinOffersProvider } from "@/components/skins/SkinOffers";
import { SkinPriceBlock } from "@/components/skins/SkinPriceBlock";
import { SkinWearPicker } from "@/components/skins/SkinWearPicker";
import { routing } from "@/i18n/routing";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";
import { skinFaq, skinFullName, skinProductLd } from "@/lib/skin-seo";
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
  const name = skinFullName(item);
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  // "купить X в Узбекистане за 40 000 сум": the query people type. No price, no "от —":
  // the copy drops the price rather than print a hole.
  const title =
    price !== null ? t("meta.itemTitle", { name, price }) : t("meta.itemTitleNoPrice", { name });
  const description =
    price !== null && item.count > 0
      ? t("meta.itemDescription", { name, price, count: item.count })
      : t("meta.itemDescriptionNoPrice", { name });
  const path = `/skins/${slug}`;
  const ogImage = `/og/${locale}${path}`;
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
      // The generated card (`app/og/...`): weapon, finish, price on the item art.
      images: [{ url: ogImage, width: 1200, height: 630 }],
      ...ogLocale(locale),
    },
    twitter: { card: "summary_large_image", title, description, images: [ogImage] },
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
  const url = localeUrl(locale, `/skins/${item.slug}`);
  const productLd = skinProductLd(item, url);
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: t("market"), item: localeUrl(locale, "/skins") },
      { "@type": "ListItem", position: 2, name: skinFullName(item), item: url },
    ],
  };
  // The other wears and the facts: under the picture on wide screens, under the price on
  // phones (rendered once per breakpoint).
  const details = (
    <>
      {worn && item.family.length > 1 && (
        <div className="space-y-2">
          <h2 className="text-[15px] font-bold">{t("otherWears")}</h2>
          <SkinWearPicker family={item.family} current={item} locale={locale} />
        </div>
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
    </>
  );

  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6">
      {productLd && <JsonLd data={productLd} />}
      <JsonLd data={breadcrumbLd} />
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
        <section className="border-border bg-card grid gap-6 rounded-2xl border p-4 sm:p-5 md:grid-cols-2 md:gap-8 md:p-8">
          {/* Left: the picked offer on the picture; on wide screens the wears and facts
              fill the space under it. Right: name, price, buying. On phones the order is
              picture → name and price → wears and facts → buying. */}
          <div className="space-y-5">
            <SkinHero
              image={item.image_url}
              name={item.name}
              exterior={item.exterior}
              rarityColor={item.rarity_color}
            />
            <div className="hidden space-y-5 md:block">{details}</div>
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
              steamUsd={item.steam_price_usd}
              steamUrl={steamMarketUrl(item.name)}
              locale={locale}
              buyable={Boolean(item.buy_sku_id)}
            />
            <div className="space-y-5 md:hidden">{details}</div>
            {item.buy_sku_id && (
              <SkinBuyPanel skuId={item.buy_sku_id} slug={item.slug} locale={locale} />
            )}
          </div>
        </section>

        {worn && (
          <section className="mt-8">
            <h2 className="mb-3 text-[17px] font-bold">
              {t("offers")}{" "}
              <span className="text-tx-dim text-[14px] tabular-nums">{item.count}</span>
            </h2>
            <SkinListings
              locale={locale}
              buyable={Boolean(item.buy_sku_id)}
              image={item.image_url}
              exterior={item.exterior}
            />
          </section>
        )}
      </SkinOffersProvider>

      {item.buy_sku_id && <SkinHowItWorks />}
      <SkinFaq title={t("faq.title")} entries={skinFaq(item, t, locale)} />
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
