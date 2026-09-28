import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { SkinCard } from "@/components/skins/SkinCard";
import { SkinCategoryBar } from "@/components/skins/SkinCategoryBar";
import { SkinFilters } from "@/components/skins/SkinFilters";
import { SkinSearch } from "@/components/skins/SkinSearch";
import { SkinSort } from "@/components/skins/SkinSort";
import { routing } from "@/i18n/routing";
import { alternates, GEO_META, localeUrl, ogLocale, pathFor, ROBOTS } from "@/lib/seo";
import { getSkinFacets, getSkinsPage, parseSkinQuery, skinQueryString } from "@/lib/skins";

const PATH = "/skins";

interface Props {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const filtered = Object.keys(await searchParams).length > 0;
  return {
    title: t("meta.title"),
    description: t("meta.description"),
    alternates: alternates(locale, PATH),
    other: GEO_META,
    // A filtered view is a duplicate of the hub for a crawler.
    robots: filtered ? { index: false, follow: true } : ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title: t("meta.title"),
      url: localeUrl(locale, PATH),
      ...ogLocale(locale),
    },
  };
}

export default async function SkinsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations("web.skins");
  const query = parseSkinQuery(await searchParams);
  const [page, facets] = await Promise.all([getSkinsPage(locale, query), getSkinFacets(locale)]);
  if (facets === null) notFound(); // the section is off (API 404) or unreachable

  return (
    <main className="mx-auto min-h-screen max-w-[1320px] px-4 pb-28 pt-[104px] sm:px-6 lg:flex lg:gap-6">
      <aside className="hidden lg:block lg:w-64 lg:shrink-0">
        <div className="border-border bg-card sticky top-24 rounded-xl border p-4">
          <p className="mb-4 text-[15px] font-bold">{t("filters")}</p>
          <SkinFilters query={query} facets={facets} locale={locale} />
        </div>
      </aside>
      <section className="min-w-0 flex-1">
        <h1 className="font-display mb-4 text-2xl font-bold">{t("title")}</h1>
        <div className="mb-3 flex flex-col gap-3 sm:flex-row">
          <SkinSearch initial={query.q ?? ""} locale={locale} query={query} />
          <SkinSort query={query} locale={locale} />
        </div>
        <SkinCategoryBar query={query} facets={facets} locale={locale} items={page.items} />
        <details className="border-border bg-card mt-3 rounded-xl border p-4 lg:hidden">
          <summary className="cursor-pointer text-[15px] font-bold">{t("filters")}</summary>
          <div className="mt-4">
            <SkinFilters query={query} facets={facets} locale={locale} />
          </div>
        </details>
        {page.items.length === 0 ? (
          <p className="text-tx-mute py-16 text-center">{t("empty")}</p>
        ) : (
          <ul className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {page.items.map((item) => (
              <li key={item.slug}>
                <SkinCard item={item} locale={locale} />
              </li>
            ))}
          </ul>
        )}
        {page.next_cursor && (
          <Link
            href={pathFor(locale, PATH) + skinQueryString(query, { cursor: page.next_cursor })}
            className="border-border mx-auto mt-6 block w-fit rounded-xl border px-6 py-3 font-semibold"
          >
            {t("loadMore")}
          </Link>
        )}
      </section>
    </main>
  );
}
