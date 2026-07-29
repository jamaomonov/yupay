import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { routing } from "@/i18n/routing";
import { alternates, ogLocale, pathFor, ROBOTS } from "@/lib/seo";

const DOCS = ["terms", "privacy", "refunds", "imprint"] as const;
type Doc = (typeof DOCS)[number];

interface Section {
  h: string;
  p: string;
}

function isDoc(value: string): value is Doc {
  return (DOCS as readonly string[]).includes(value);
}

export function generateStaticParams() {
  return DOCS.map((doc) => ({ doc }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; doc: string }>;
}): Promise<Metadata> {
  const { locale, doc } = await params;
  if (!hasLocale(routing.locales, locale) || !isDoc(doc)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.legal");
  const title = t(`${doc}.title`);
  const description = t(`${doc}.intro`);
  return {
    title,
    description,
    alternates: alternates(locale, `/legal/${doc}`),
    robots: ROBOTS,
    openGraph: { type: "website", siteName: "YuPay", title, description, ...ogLocale(locale) },
  };
}

export default async function LegalPage({
  params,
}: {
  params: Promise<{ locale: string; doc: string }>;
}) {
  const { locale, doc } = await params;
  if (!isDoc(doc)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations("web.legal");
  const sections = t.raw(`${doc}.sections`) as Section[];

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      <div className="mx-auto max-w-[760px] px-6 sm:px-10">
        <nav className="text-tx-dim mb-7 flex items-center gap-1.5 font-mono text-[11px]">
          <Link href={pathFor(locale)} className="hover:text-tx-mute transition">
            {t("home")}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{t(`${doc}.title`)}</span>
        </nav>

        <h1 className="font-display text-[clamp(2rem,4.5vw,3rem)] font-extrabold leading-[1] tracking-[-0.03em]">
          {t(`${doc}.title`)}
        </h1>
        <p className="text-tx-dim mt-3 font-mono text-xs">
          {t("updatedLabel")} {t(`${doc}.updated`)}
        </p>
        <p className="text-tx-mute mt-6 text-[15px] leading-relaxed sm:text-base">
          {t(`${doc}.intro`)}
        </p>

        <div className="mt-10 flex flex-col gap-8">
          {sections.map((s, i) => (
            <section key={i}>
              <h2 className="font-display text-lg font-bold tracking-[-0.015em]">{s.h}</h2>
              <p className="text-tx-mute mt-2 text-[15px] leading-relaxed">{s.p}</p>
            </section>
          ))}
        </div>

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
