import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { routing } from "@/i18n/routing";
import { LEGAL_DOCS } from "@/lib/legal";
import { alternates, ogLocale, pathFor, ROBOTS } from "@/lib/seo";

/**
 * The index over the legal documents.
 *
 * It exists because a single address for "our documents" is what gets handed
 * around — linked from the Mini App profile, pasted into a support reply, given
 * to an acquirer during onboarding. Five separate URLs are not something anyone
 * quotes, and `/legal` was the obvious guess that answered 404.
 */

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.legal");
  const title = t("index.title");
  const description = t("index.intro");
  return {
    title,
    description,
    alternates: alternates(locale, "/legal"),
    robots: ROBOTS,
    openGraph: { type: "website", siteName: "YuPay", title, description, ...ogLocale(locale) },
  };
}

export default async function LegalIndexPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("web.legal");
  const tn = await getTranslations("web.nav");

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <div className="mx-auto max-w-[760px] px-6 sm:px-10">
        <nav
          aria-label={tn("breadcrumbLabel")}
          className="text-tx-dim mb-7 flex items-center gap-1.5 font-mono text-[11px]"
        >
          <Link href={pathFor(locale)} className="hover:text-tx-mute transition">
            {t("home")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{t("index.title")}</span>
        </nav>

        <h1 className="font-display text-[clamp(2rem,4.5vw,3rem)] font-extrabold leading-[1] tracking-[-0.03em]">
          {t("index.title")}
        </h1>
        <p className="text-tx-mute mt-6 text-[15px] leading-relaxed sm:text-base">
          {t("index.intro")}
        </p>

        {/* Each document carries its own one-line summary already — the same
            `intro` the document itself opens with — so the index says what a
            reader is about to open instead of listing five bare titles. */}
        <ul className="mt-10 flex flex-col gap-3">
          {LEGAL_DOCS.map((doc) => (
            <li key={doc}>
              <Link
                href={pathFor(locale, `/legal/${doc}`)}
                className="border-border hover:border-tx-dim group flex items-start gap-4 rounded-xl border p-5 transition"
              >
                <span className="min-w-0 flex-1">
                  <span className="font-display group-hover:text-primary block text-lg font-bold tracking-[-0.015em] transition">
                    {t(`${doc}.title`)}
                  </span>
                  <span className="text-tx-mute mt-1.5 block text-sm leading-relaxed">
                    {t(`${doc}.intro`)}
                  </span>
                  <span className="text-tx-dim mt-2 block font-mono text-[11px]">
                    {t("updatedLabel")} {t(`${doc}.updated`)}
                  </span>
                </span>
                <ChevronRight
                  size={18}
                  aria-hidden="true"
                  className="text-tx-dim group-hover:text-primary mt-1 shrink-0 transition"
                />
              </Link>
            </li>
          ))}
        </ul>

        <div className="border-border mt-12 border-t pt-8">
          <Link
            href={pathFor(locale, "/store")}
            className="text-primary text-sm font-semibold underline-offset-4 hover:underline"
          >
            {t("backToStore")}
          </Link>
        </div>
      </div>
    </main>
  );
}
