import {
  ArrowRight,
  Braces,
  Check,
  Repeat2,
  RotateCcw,
  Search,
  Smartphone,
  Ticket,
  UserPlus,
  UserSearch,
  Webhook,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { DocsLinks } from "@/components/landing/DocsLinks";
import { Faq } from "@/components/landing/Faq";
import { Hero } from "@/components/landing/Hero";
import { PageFrame } from "@/components/landing/PageFrame";
import { CARD, PAGE_MAIN, SECTION_HEADING } from "@/components/landing/styles";
import { faqPage, organization, service, website } from "@/lib/jsonld";
import { pathFor } from "@/lib/locale-href";
import { alternates, localeUrl, ogAlt, ROBOTS, SITE, social } from "@/lib/seo";

export const revalidate = 3600;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.meta" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: alternates(locale, ""),
    robots: ROBOTS,
    ...social(locale, {
      alt: await ogAlt(locale),
      url: localeUrl(locale),
      title: t("title"),
      description: t("description"),
    }),
  };
}

export default async function Landing({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.landing");
  // The five questions the landing shows come from the same namespace the
  // `/faq` page reads, so the two can never answer the same question
  // differently.
  const tFaq = await getTranslations("merchant.faq");

  const steps = [
    { icon: UserPlus, title: t("step1Title"), body: t("step1Body") },
    { icon: Search, title: t("step2Title"), body: t("step2Body") },
    { icon: Ticket, title: t("step3Title"), body: t("step3Body") },
  ];

  const promises = [
    { icon: Zap, title: t("dev1Title"), body: t("dev1Body") },
    { icon: Repeat2, title: t("dev2Title"), body: t("dev2Body") },
    { icon: Webhook, title: t("dev3Title"), body: t("dev3Body") },
    { icon: UserSearch, title: t("dev4Title"), body: t("dev4Body") },
    { icon: RotateCcw, title: t("dev5Title"), body: t("dev5Body") },
  ];

  // String suffixes, not numbers: the key is built by concatenation and a
  // number in a template literal is a lint warning the repo does not carry.
  const faq = ["1", "2", "3", "4", "5"].map((n) => ({ q: tFaq(`q${n}`), a: tFaq(`a${n}`) }));

  return (
    <PageFrame locale={locale}>
      {/* Site-wide structured data for the landing, one script carrying all
          four nodes via @graph. Organization points back at the storefront's
          own record by `@id` rather than redeclaring it — this is a B2B
          surface of the same business, not a second one. */}
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@graph": [organization(), website(SITE), service(SITE, t("programName")), faqPage(faq)],
        }}
      />
      <main className={PAGE_MAIN}>
        <Hero locale={locale} />

        {/* The paragraph an assistant lifts whole. It stays directly under the
            hero and before every other block: the first prose on the page is
            what gets quoted, and a page that buries its own description gets
            described by somebody else. */}
        <p className="text-tx-mute mt-14 max-w-3xl text-[15px] leading-relaxed">{t("answer")}</p>

        <section className="mt-16">
          <h2 className={SECTION_HEADING}>{t("forWhoHeading")}</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {[
              {
                icon: Smartphone,
                title: t("forWhoTgTitle"),
                body: t("forWhoTgBody"),
                cta: t("forWhoTgCta"),
                // The channel admin stays on this page; the developer leaves
                // for the page written for them.
                href: "#how",
              },
              {
                icon: Braces,
                title: t("forWhoDevTitle"),
                body: t("forWhoDevBody"),
                cta: t("forWhoDevCta"),
                href: "/api",
              },
            ].map(({ icon: Icon, title, body, cta, href }) => (
              <div key={title} className={CARD}>
                <div className="text-primary-ink">
                  <Icon size={20} />
                </div>
                <h3 className="mt-3 text-lg font-semibold">{title}</h3>
                <p className="text-tx-mute mt-2 text-sm leading-relaxed">{body}</p>
                <Link
                  href={href.startsWith("#") ? href : pathFor(locale, href)}
                  className="text-primary-ink mt-4 inline-flex items-center gap-1.5 text-sm font-semibold"
                >
                  {cta} <ArrowRight size={14} />
                </Link>
              </div>
            ))}
          </div>
        </section>

        <section id="how" className="mt-20 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{t("stepsHeading")}</h2>
          <ol className="mt-7 grid gap-4 sm:grid-cols-3">
            {steps.map(({ icon: Icon, title, body }, index) => (
              <li key={title} className={CARD}>
                <div className="text-primary-ink flex items-center gap-2">
                  <Icon size={18} />
                  <span className="font-mono text-xs">{String(index + 1).padStart(2, "0")}</span>
                </div>
                <h3 className="mt-3 font-semibold">{title}</h3>
                <p className="text-tx-mute mt-2 text-sm leading-relaxed">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* `id="catalog"`: the 404 page links here — the public site has no
            catalogue page of its own, the full list opens after sign-up. */}
        <section id="catalog" className="mt-20 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{t("sectionsHeading")}</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {[
              { name: t("sectionTopups"), body: t("sectionTopupsBody") },
              { name: t("sectionVouchers"), body: t("sectionVouchersBody") },
              { name: t("sectionTelegram"), body: t("sectionTelegramBody") },
              { name: t("sectionSteam"), body: t("sectionSteamBody") },
            ].map(({ name, body }) => (
              <div key={name} className="border-border bg-card rounded-xl border p-5">
                <p className="font-semibold">{name}</p>
                <p className="text-tx-mute mt-2 text-[13px] leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-border bg-card mt-20 rounded-2xl border p-8">
          <h2 className="text-xl font-semibold tracking-tight">{t("wrongIdHeading")}</h2>
          <p className="text-tx-mute mt-3 max-w-3xl text-sm leading-relaxed">{t("wrongIdBody")}</p>
        </section>

        <section id="developers" className="mt-20 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{t("devHeading")}</h2>
          <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {promises.map(({ icon: Icon, title, body }) => (
              <div key={title} className={CARD}>
                <div className="text-primary-ink">
                  <Icon size={18} />
                </div>
                <h3 className="mt-3 font-semibold">{title}</h3>
                <p className="text-tx-mute mt-2 text-[13px] leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
          <p className="text-tx-dim mt-5 text-[13px]">{t("devTest")}</p>
          <DocsLinks locale={locale} />
        </section>

        <section className="mt-20">
          <h2 className={SECTION_HEADING}>{t("compareHeading")}</h2>
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {["1", "2", "3", "4", "5"].map((n) => (
              <li key={n} className="text-tx-mute flex gap-2.5 text-sm leading-relaxed">
                <Check size={16} aria-hidden="true" className="text-primary-ink mt-0.5 shrink-0" />
                {t(`compare${n}`)}
              </li>
            ))}
          </ul>
        </section>

        <section id="faq" className="mt-20 scroll-mt-8">
          <h2 className={SECTION_HEADING}>{t("faqHeading")}</h2>
          <Faq items={faq} className="mt-6" />
          <Link
            href={pathFor(locale, "/faq")}
            className="text-primary-ink mt-5 inline-flex items-center gap-1.5 text-sm font-semibold"
          >
            {t("faqAll")} <ArrowRight size={14} />
          </Link>
        </section>

        <section className="mt-20">
          <h2 className={SECTION_HEADING}>{t("trustHeading")}</h2>
          {/* Facts a reseller can check, and nothing else: no legal details
              (the owner's call), no figures we do not publish, no reviews we
              do not have. Each line is something the product already does. */}
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {(
              ["trustWhat", "trustPay", "trustDelivery", "trustCheck", "trustSupport"] as const
            ).map((key) => (
              <li key={key} className="text-tx-mute flex gap-2.5 text-sm leading-relaxed">
                <Check size={16} aria-hidden="true" className="text-primary-ink mt-0.5 shrink-0" />
                {t(key)}
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-[13px]">
            <a href="https://yupay.uz" className="text-primary-ink font-semibold">
              {t("trustRetail")}
            </a>
            <Link href={pathFor(locale, "/offer")} className="text-primary-ink font-semibold">
              {t("trustOffer")}
            </Link>
          </div>
        </section>

        <section className="border-border bg-card mt-20 rounded-2xl border p-8">
          <h2 className="text-xl font-semibold tracking-tight">{t("supportHeading")}</h2>
          <p className="text-tx-mute mt-2 text-sm">{t("supportBody")}</p>
          <a
            href="https://t.me/yupay_support"
            className="border-border rounded-btn mt-5 inline-flex items-center border px-4 py-2.5 text-sm font-semibold"
          >
            {t("supportCta")}
          </a>
        </section>
      </main>
    </PageFrame>
  );
}
