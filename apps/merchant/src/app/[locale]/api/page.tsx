import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { DocsLinks } from "@/components/landing/DocsLinks";
import { Faq } from "@/components/landing/Faq";
import { PageFrame } from "@/components/landing/PageFrame";
import { LEAD, PAGE_MAIN, SECTION_HEADING } from "@/components/landing/styles";
import { breadcrumbs, faqPage, techArticle } from "@/lib/jsonld";
import { pathFor } from "@/lib/locale-href";
import { alternates, dayStamp, localeUrl, ogLocale, OPENAPI_URL, ROBOTS } from "@/lib/seo";

const PATH = "/api";

export const revalidate = 3600;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.pages.api" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: {
      ...alternates(locale, PATH),
      // The strongest asset on this page is that the schema is public and
      // live. An `application/json` alternate in the head is how a crawler —
      // or an assistant asked to "write me a client" — finds it without
      // reading the prose first.
      types: { "application/json": OPENAPI_URL },
    },
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
 * Method and path are code, not copy: they are the same in every locale and
 * translating them would be a bug. Only the "what for" column is a string.
 */
const ENDPOINTS = [
  { method: "GET", path: "/merchant/v1/me", key: "epMe" },
  { method: "GET", path: "/merchant/v1/catalog", key: "epCatalog" },
  { method: "POST", path: "/merchant/v1/orders", key: "epOrder" },
  { method: "GET", path: "/merchant/v1/orders/{merchant_order_id}", key: "epStatus" },
  { method: "POST", path: "/merchant/v1/validate/player", key: "epValidate" },
  { method: "GET", path: "/merchant/v1/transactions", key: "epTransactions" },
];

/** The four a developer asks. The channel-admin questions live on
 *  `/telegram`; `/faq` carries all twelve. */
const FAQ_KEYS = ["3", "4", "10", "12"];

/**
 * `/api` — the intent page for "do you have an API, and what does it do".
 *
 * Deliberately not `/docs`: that is the reference ("how do I sign a
 * request"), this is the answer to the question someone types into a search
 * box before they have decided to integrate. Both are indexed and each links
 * to the other. The section bodies reuse the landing's `dev*Body` strings
 * rather than restating them — one sentence about idempotency, in one place.
 */
export default async function ApiPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.pages.api");
  const tPages = await getTranslations("merchant.pages");
  const tLanding = await getTranslations("merchant.landing");
  const tFaq = await getTranslations("merchant.faq");

  const items = FAQ_KEYS.map((n) => ({ q: tFaq(`q${n}`), a: tFaq(`a${n}`) }));

  // Same truncated-to-the-day stamp the sitemap's `lastModified` uses — see
  // `dayStamp()`'s doc for why.
  const dateModified = dayStamp();

  const sections = [
    { heading: t("h2Is"), body: t("bodyIs") },
    { heading: t("h2Idem"), body: tLanding("dev2Body") },
    { heading: t("h2Hooks"), body: tLanding("dev3Body") },
    { heading: t("h2Check"), body: tLanding("dev4Body") },
    { heading: t("h2Refund"), body: tLanding("dev5Body") },
    { heading: t("h2Pubg"), body: t("bodyPubg") },
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
            techArticle({
              headline: t("h1"),
              description: t("description"),
              about: "Game top-up API",
              url: localeUrl(locale, PATH),
              dateModified: dateModified.toISOString(),
            }),
            faqPage(items),
          ],
        }}
      />
      <main className={PAGE_MAIN}>
        <h1 className="font-display max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
          {t("h1")}
        </h1>
        <p className={LEAD}>{t("answer")}</p>

        <section className="mt-14">
          <h2 className={SECTION_HEADING}>{t("h2Six")}</h2>
          {/* The one wide block on the page, so it scrolls inside itself
              rather than making the whole page scroll sideways on a phone. */}
          <div className="border-border mt-6 overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[34rem] border-collapse text-left text-[13px]">
              <thead className="text-tx-dim border-border border-b">
                <tr>
                  <th className="px-4 py-3 font-semibold">{t("tableMethod")}</th>
                  <th className="px-4 py-3 font-semibold">{t("tablePath")}</th>
                  <th className="px-4 py-3 font-semibold">{t("tablePurpose")}</th>
                </tr>
              </thead>
              <tbody>
                {ENDPOINTS.map(({ method, path, key }) => (
                  <tr key={path} className="border-border border-b last:border-0">
                    <td className="text-primary-ink px-4 py-3 font-mono font-semibold">{method}</td>
                    <td className="px-4 py-3 font-mono">{path}</td>
                    <td className="text-tx-mute px-4 py-3">{t(key)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {sections.map(({ heading, body }) => (
          <section key={heading} className="mt-14">
            <h2 className={SECTION_HEADING}>{heading}</h2>
            <p className="text-tx-mute mt-3 max-w-3xl text-sm leading-relaxed">{body}</p>
          </section>
        ))}

        <section className="border-border bg-card mt-14 rounded-2xl border p-8">
          <h2 className={SECTION_HEADING}>{t("h2Start")}</h2>
          <p className="text-tx-mute mt-3 max-w-3xl text-sm leading-relaxed">{t("bodyStart")}</p>
          <DocsLinks locale={locale} />
        </section>

        <section id="faq" className="mt-16 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{tLanding("faqHeading")}</h2>
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
        </div>
      </main>
    </PageFrame>
  );
}
