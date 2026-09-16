import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { GiftsBrowser } from "@/components/gifts/GiftsBrowser";
import { HotOffers } from "@/components/gifts/HotOffers";
import { JsonLd } from "@/components/JsonLd";
import { AboutText } from "@/components/store/AboutText";
import { HighlightChips } from "@/components/store/HighlightChips";
import { routing } from "@/i18n/routing";
import { getBrandDetail } from "@/lib/catalog";
import { getGiftsHot, getGiftsPage } from "@/lib/gifts";
import {
  alternates,
  firstNonEmpty,
  GEO_META,
  localeUrl,
  ogLocale,
  pathFor,
  ROBOTS,
} from "@/lib/seo";

const PATH = "/store/steam-gifts";
/** The catalog brand this hub is the storefront for. Its `brand_translations`
 *  row carries the prose and its `brand_faqs` the questions — the same content
 *  tables every other brand page reads, seeded by
 *  `scripts/seed/steam_gifts_seo.sql`. This page had been rendering none of
 *  it: the hub is a bespoke route (the static `steam-gifts` segment shadows
 *  `[brandSlug]`), so it never inherited the brand page's SEO furniture. */
const BRAND_SLUG = "steam-gifts";
const CURRENCY = "UZS";

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
  const [hot, firstPage, brand] = await Promise.all([
    getGiftsHot(locale),
    getGiftsPage(locale),
    // `getBrandDetail` is already null-safe (`apiGetOrNull`), so an API that
    // predates the brand — or one whose seed has not been applied yet — costs
    // the prose blocks and nothing else.
    getBrandDetail(BRAND_SLUG, locale, CURRENCY),
  ]);
  const isDark = hot.length === 0 && firstPage.items.length === 0;

  const tStore = await getTranslations("web.store");
  const highlights = brand?.highlights ?? [];
  const about = firstNonEmpty(brand?.description, brand?.short_description);
  const faqs = brand?.faqs ?? [];
  const hasHowTo = (brand?.instructions ?? "").trim() !== "";
  // FAQPage structured data — the thing that can win the questions their own
  // rows in the results page. Emitted only when there are questions to answer:
  // an empty `mainEntity` is a structured-data error, not a neutral no-op.
  const faqLd =
    faqs.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqs.map((f) => ({
            "@type": "Question",
            name: f.question,
            acceptedAnswer: { "@type": "Answer", text: f.answer },
          })),
        }
      : undefined;

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
      {faqLd && <JsonLd data={faqLd} />}

      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <h1 className="font-display max-w-[760px] text-[clamp(2.2rem,5vw,3.6rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
          {t("hero.title")}
        </h1>
        <p className="text-tx-mute mt-5 max-w-[620px] text-base leading-relaxed sm:text-lg">
          {t("hero.subtitle")}
        </p>

        {/* `on-surface`: this hub has no hero photograph, and the over-image
            styling the brand pages use is white-on-white here in light mode. */}
        {highlights.length > 0 && (
          <div className="mt-6 flex flex-wrap gap-2">
            <HighlightChips items={highlights} variant="on-surface" />
          </div>
        )}

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

        {/* Below the catalog, in the brand page's own order: prose, then the
            guide link, then the questions. A crawler reads it wherever it
            sits, and a buyer who already knows what they want is not made to
            scroll past an essay to reach the search box. */}
        {about && (
          <section className="mt-16 scroll-mt-[88px]">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {tStore("aboutTitle")}
            </h2>
            <AboutText text={about} moreLabel={tStore("readMore")} lessLabel={tStore("readLess")} />
          </section>
        )}

        {hasHowTo && (
          <Link
            href={pathFor(locale, `${PATH}/how-to`)}
            className="text-tx-mute hover:text-foreground mt-8 inline-flex items-center gap-1 text-[15px] font-semibold transition"
          >
            {tStore("howToLink")}
            <ChevronRight size={15} />
          </Link>
        )}

        {faqs.length > 0 && (
          <section className="mt-14 scroll-mt-[88px]">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {tStore("faqTitle")}
            </h2>
            <div className="border-border/70 mt-5 border-y">
              {faqs.map((f) => (
                <details key={f.id} className="border-border/70 group border-b last:border-b-0">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
                    {f.question}
                    <ChevronRight
                      size={16}
                      className="text-tx-dim shrink-0 transition group-open:rotate-90"
                    />
                  </summary>
                  <p className="text-tx-mute -mt-1 pb-4 pr-8 text-[15px] leading-relaxed">
                    {f.answer}
                  </p>
                </details>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
