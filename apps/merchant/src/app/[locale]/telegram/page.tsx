import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { Faq } from "@/components/landing/Faq";
import { PageFrame } from "@/components/landing/PageFrame";
import { LEAD, PAGE_MAIN, SECTION_HEADING } from "@/components/landing/styles";
import { breadcrumbs, faqPage } from "@/lib/jsonld";
import { pathFor } from "@/lib/locale-href";
import { alternates, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";

const PATH = "/telegram";

/** Hourly, like every other public page: the copy is static, but the page
 *  should pick up a string change without waiting for a deploy. */
export const revalidate = 3600;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.pages.telegram" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: alternates(locale, PATH),
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title: t("title"),
      description: t("description"),
      url: localeUrl(locale, PATH),
      ...ogLocale(locale),
    },
  };
}

/**
 * The eight questions this page shows. Not all twelve: `/faq` carries the
 * full set, and two pages repeating the same list verbatim compete for the
 * same snippet. These are the ones a channel admin asks — pricing access,
 * wrong IDs, stuck orders, working without code — and the developer-only
 * ones (q3, q4) are left to `/api`.
 */
const FAQ_KEYS = ["1", "2", "5", "6", "7", "9", "10", "12"];

/**
 * `/telegram` — the landing page for "where do I get stock for my Telegram
 * channel".
 *
 * One of two audience pages (see `/api` for the other). The split is the
 * whole point: a channel admin and a developer type different words into a
 * search box, and a single page answering both ranks for neither. Everything
 * here is written for someone who does not write code — the word "endpoint"
 * appears nowhere.
 */
export default async function TelegramPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.pages.telegram");
  const tPages = await getTranslations("merchant.pages");
  const tLanding = await getTranslations("merchant.landing");
  const tFaq = await getTranslations("merchant.faq");

  // The same array is rendered and marked up, so the FAQPage nodes can never
  // describe a question a visitor cannot see.
  const items = FAQ_KEYS.map((n) => ({ q: tFaq(`q${n}`), a: tFaq(`a${n}`) }));

  const sections = [
    { heading: t("h2Instead"), body: t("bodyInstead") },
    { heading: t("h2Day"), body: t("bodyDay") },
    { heading: t("h2WrongId"), body: t("bodyWrongId") },
    { heading: t("h2Stuck"), body: t("bodyStuck") },
  ];

  return (
    <PageFrame locale={locale}>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@graph": [
            breadcrumbs([
              { name: tPages("home"), url: localeUrl(locale) },
              { name: t("h1"), url: localeUrl(locale, PATH) },
            ]),
            faqPage(items),
          ],
        }}
      />
      <main className={PAGE_MAIN}>
        <h1 className="font-display max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
          {t("h1")}
        </h1>
        {/* First prose on the page, and deliberately so: this is the
            paragraph an assistant quotes when asked the page's own question. */}
        <p className={LEAD}>{t("answer")}</p>

        {sections.map(({ heading, body }) => (
          <section key={heading} className="mt-14">
            <h2 className={SECTION_HEADING}>{heading}</h2>
            <p className="text-tx-mute mt-3 max-w-3xl text-sm leading-relaxed">{body}</p>
          </section>
        ))}

        <section id="faq" className="mt-16 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{t("h2Faq")}</h2>
          <Faq items={items} className="mt-6" />
        </section>

        <div className="mt-12 flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
          <Link
            href={pathFor(locale, "/register")}
            className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 font-semibold"
          >
            {tLanding("ctaPrimary")}
            <ArrowRight size={16} />
          </Link>
          <Link href={pathFor(locale, "/faq")} className="text-primary-ink font-semibold">
            {tLanding("faqAll")}
          </Link>
          {/* Back to the landing's own steps rather than repeating them here:
              one description of the three steps, one page that owns it. */}
          <Link href={`${pathFor(locale, "/")}#how`} className="text-tx-mute">
            {tLanding("ctaSecondary")}
          </Link>
        </div>
      </main>
    </PageFrame>
  );
}
