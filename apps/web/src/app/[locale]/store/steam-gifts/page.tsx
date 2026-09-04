import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { GiftsBrowser } from "@/components/gifts/GiftsBrowser";
import { HotOffers } from "@/components/gifts/HotOffers";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { getGiftsHot, getGiftsPage } from "@/lib/gifts";
import { alternates, GEO_META, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";

const PATH = "/store/steam-gifts";

export const revalidate = 300;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.gifts");
  const title = t("meta.title");
  const description = t("meta.description");
  return {
    title,
    description,
    alternates: alternates(locale, PATH),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, PATH),
      ...ogLocale(locale),
    },
  };
}

export default async function SteamGiftsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("web.gifts");

  // Both fetchers are dark-deploy-safe (see `lib/gifts.ts`): the whole
  // `/gifts/*` API surface 404s while `steam_gifts_enabled` is off, and both
  // calls collapse to an empty result rather than throwing.
  const [hot, firstPage] = await Promise.all([getGiftsHot(locale), getGiftsPage(locale)]);
  const isDark = hot.length === 0 && firstPage.items.length === 0;

  // ItemList of the hot offers only — spec §5: the full catalog runs ~4k
  // items with live prices, and a JSON-LD payload that size would churn
  // every crawl for numbers that are stale within minutes.
  const hotListLd =
    hot.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "ItemList",
          name: t("hot.title"),
          itemListElement: hot.map((app, i) => ({
            "@type": "ListItem",
            position: i + 1,
            url: localeUrl(locale, `/store/steam-gifts/${String(app.app_id)}`),
            name: app.name,
          })),
        }
      : undefined;

  const steps = [t("hero.step1"), t("hero.step2"), t("hero.step3")];

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      {hotListLd && <JsonLd data={hotListLd} />}

      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <h1 className="font-display max-w-[760px] text-[clamp(2.2rem,5vw,3.6rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
          {t("hero.title")}
        </h1>
        <p className="text-tx-mute mt-5 max-w-[620px] text-base leading-relaxed sm:text-lg">
          {t("hero.subtitle")}
        </p>

        <section className="mt-10">
          <h2 className="font-display text-lg font-bold tracking-[-0.02em]">
            {t("hero.howTitle")}
          </h2>
          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {steps.map((step, i) => (
              <div key={i} className="border-border bg-card rounded-lg border p-6">
                <div className="bg-primary/10 text-primary flex h-9 w-9 items-center justify-center rounded-full font-mono text-[14px] font-bold">
                  {i + 1}
                </div>
                <p className="text-tx-mute mt-4 text-[14px] leading-relaxed">{step}</p>
              </div>
            ))}
          </div>
        </section>

        {isDark ? (
          <p className="text-tx-mute mt-16 text-center text-[15px]">{t("comingSoon")}</p>
        ) : (
          <>
            <HotOffers items={hot} locale={locale} />
            <GiftsBrowser locale={locale} initial={firstPage} hasHotOffers={hot.length > 0} />
          </>
        )}
      </div>
    </main>
  );
}
