import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";
import { categoryPath, findWeapon, isSkinCategory, weaponPath } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage, skinQueryString } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; weapon: string }>;
}

/** The weapon behind the slug and its numbers, or `null` when the catalogue has none. */
async function load(locale: string, slug: string) {
  const facets = await getSkinFacets(locale);
  const weapon = facets ? findWeapon(facets, slug) : null;
  if (!weapon) return null;
  const cheapest = await getSkinsPage(locale, { sort: "price", weapon: weapon.value });
  const first = cheapest.items[0];
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  const category = first && isSkinCategory(first.category) ? first.category : null;
  return { weapon, from, category };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, weapon: slug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const data = await load(locale, slug);
  if (!data) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const w = data.weapon.value;
  const title = t("landing.weaponTitle", { weapon: w });
  const description = data.from
    ? t("landing.description", {
        name: t("landing.skinsOf", { weapon: w }),
        count: data.weapon.count,
        price: data.from,
      })
    : t("meta.description");
  const path = weaponPath(w);
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
      ...ogLocale(locale),
    },
  };
}

export default async function SkinWeaponPage({ params }: Props) {
  const { locale, weapon: slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const data = await load(locale, slug);
  if (!data) notFound();
  const t = await getTranslations("web.skins");
  const w = data.weapon.value;
  const query = {
    sort: "popular" as const,
    weapon: w,
    ...(data.category ? { category: data.category } : {}),
  };
  const page = await getSkinsPage(locale, query);
  return (
    <SkinLanding
      locale={locale}
      h1={t("landing.weaponH1", { weapon: w })}
      intro={data.from ? t("landing.intro", { count: data.weapon.count, price: data.from }) : null}
      items={page.items}
      allHref={pathFor(locale, "/skins") + skinQueryString(query, {})}
      crumbs={[
        { name: t("market"), path: "/skins" },
        ...(data.category
          ? [
              {
                name: t("landing.categoryH1", { name: t(`category.${data.category}`) }),
                path: categoryPath(data.category),
              },
            ]
          : []),
        { name: t("landing.weaponH1", { weapon: w }), path: weaponPath(w) },
      ]}
    />
  );
}
