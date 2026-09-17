import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { Faq } from "@/components/landing/Faq";
import { PageFrame } from "@/components/landing/PageFrame";
import { LEAD, PAGE_MAIN } from "@/components/landing/styles";
import { breadcrumbs, faqPage } from "@/lib/jsonld";
import { pathFor } from "@/lib/locale-href";
import { alternates, localeUrl, ogLocale, ROBOTS } from "@/lib/seo";

const PATH = "/faq";

export const revalidate = 3600;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.pages.faqPage" });
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

/** All twelve. This is the page that owns the full list — the landing shows
 *  five and links here, `/telegram` and `/api` show their own audience's
 *  subset. */
const FAQ_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"];

/**
 * `/faq` — every question, in one place.
 *
 * The `FAQPage` markup covers the whole list because the whole list is
 * visible: no accordion hides an answer from a crawler, `<details>` content
 * is in the DOM whether it is open or not.
 */
export default async function FaqPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.pages.faqPage");
  const tPages = await getTranslations("merchant.pages");
  const tLanding = await getTranslations("merchant.landing");
  const tFaq = await getTranslations("merchant.faq");

  const items = FAQ_KEYS.map((n) => ({ q: tFaq(`q${n}`), a: tFaq(`a${n}`) }));

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
        <p className={LEAD}>{t("answer")}</p>

        <Faq items={items} className="mt-10" />

        <div className="mt-12 flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
          <Link
            href={pathFor(locale, "/register")}
            className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 font-semibold"
          >
            {tLanding("ctaPrimary")}
            <ArrowRight size={16} />
          </Link>
          <Link href={pathFor(locale, "/telegram")} className="text-primary-ink font-semibold">
            {tLanding("navTelegram")}
          </Link>
          <Link href={pathFor(locale, "/api")} className="text-tx-mute">
            {tLanding("forWhoDevCta")}
          </Link>
        </div>
      </main>
    </PageFrame>
  );
}
