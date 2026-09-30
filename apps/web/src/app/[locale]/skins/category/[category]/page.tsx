import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinLanding } from "@/components/skins/SkinLanding";
import { routing } from "@/i18n/routing";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";
import { categoryPath, countUnit, isSkinCategory, weaponPath } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage, skinQueryString } from "@/lib/skins";

interface Props {
  params: Promise<{ locale: string; category: string }>;
}

/** The category and its numbers, or `null` when the catalogue does not have it. */
async function load(locale: string, category: string) {
  if (!isSkinCategory(category)) return null;
  const [all, scoped, cheapest] = await Promise.all([
    getSkinFacets(locale),
    getSkinFacets(locale, category),
    getSkinsPage(locale, { sort: "price", category }),
  ]);
  const facet = all?.categories.find((c) => c.value === category);
  if (!facet || !scoped) return null;
  const first = cheapest.items[0];
  const from = first ? displayPrice(locale, first.price_uzs, first.price_usd) : null;
  return { category, facet, scoped, from, cheapest: first ?? null };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, category } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const data = await load(locale, category);
  if (!data) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const name = t(`category.${data.category}`);
  const title = t("landing.categoryTitle", { name });
  const description = data.from
    ? t("landing.description", {
        // «Купить агентов», not «агенты»: the one animate noun among the categories.
        name:
          data.category === "agents"
            ? t("landing.agentsInline")
            : t("landing.categoryInline", { name: name.toLocaleLowerCase(locale) }),
        items: t("landing.count", { unit: countUnit(data.category), count: data.facet.count }),
        price: data.from,
      })
    : t("meta.description");
  const path = categoryPath(category);
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

export default async function SkinCategoryPage({ params }: Props) {
  const { locale, category } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const data = await load(locale, category);
  if (!data) notFound();
  const t = await getTranslations("web.skins");
  const cat = data.category;
  const name = t(`category.${cat}`);
  const page = await getSkinsPage(locale, { sort: "popular", category: cat });
  const items = t("landing.count", { unit: countUnit(cat), count: data.facet.count });
  // "самый дешёвый нож в кс2" is how buyers ask; the answer is live, not written.
  const faq =
    cat === "knives" && data.cheapest && data.from
      ? {
          title: t("faq.title"),
          entries: [
            {
              question: t("landing.cheapestKnifeQ"),
              answer: t("landing.cheapestKnifeA", {
                name: data.cheapest.name.replace(/^★\s*/, ""),
                price: data.from,
                items,
              }),
            },
          ],
        }
      : undefined;
  const query = { sort: "popular" as const, category: cat };
  return (
    <SkinLanding
      locale={locale}
      h1={t("landing.categoryH1", { name })}
      intro={data.from ? t("landing.intro", { items, price: data.from }) : null}
      items={page.items}
      {...(faq ? { faq } : {})}
      allHref={pathFor(locale, "/skins") + skinQueryString(query, {})}
      crumbs={[
        { name: t("market"), path: "/skins" },
        { name: t("landing.categoryH1", { name }), path: categoryPath(category) },
      ]}
      links={{
        title: t("landing.weapons"),
        items: data.scoped.weapons.map((w) => ({
          label: w.value,
          path: weaponPath(w.value),
          count: w.count,
        })),
      }}
    />
  );
}
