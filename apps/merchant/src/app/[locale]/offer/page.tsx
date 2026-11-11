import { readFile } from "node:fs/promises";
import path from "node:path";

import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { PageFrame } from "@/components/landing/PageFrame";
import { pathFor } from "@/lib/locale-href";
import { parseOffer } from "@/lib/offer";
import { alternates, localeUrl, ogAlt, ROBOTS, social } from "@/lib/seo";

export const revalidate = 3600;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.offer" });
  return {
    title: t("metaTitle"),
    description: t("metaDescription"),
    alternates: alternates(locale, "/offer"),
    robots: ROBOTS,
    ...social(locale, {
      alt: await ogAlt(locale),
      url: localeUrl(locale, "/offer"),
      title: t("metaTitle"),
      description: t("metaDescription"),
    }),
  };
}

/**
 * The public offer a reseller accepts at registration.
 *
 * Rendered from `docs/legal/merchant-offer.ru.md` rather than from the i18n
 * catalogue, because a legal document is versioned prose and not UI strings:
 * the revision a reseller accepted is recorded against their user row, so the
 * text must live somewhere a diff can show what changed between revisions.
 * The revision date shown here is read from that file, so the page and the
 * document cannot disagree about which edition this is.
 */
export default async function OfferPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.offer");

  const file = path.join(process.cwd(), "../../docs/legal/merchant-offer.ru.md");
  // NOT `.catch(() => "")`. That swallow shipped a blank contract to
  // production in all three locales — `.dockerignore` excluded `docs/`
  // wholesale, the read ENOENT'd inside the image, and the page rendered
  // over nothing while registration kept hard-blocking on "I accept the
  // offer". A missing contract must fail the build, the way the API contract
  // already does: an empty offer is worse than no offer page, because the
  // checkbox still claims consent.
  const { revision, blocks } = parseOffer(await readFile(file, "utf8"));

  return (
    <PageFrame locale={locale}>
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
        <p className="text-tx-dim mt-2 text-sm">{t("revision", { date: revision })}</p>
        {locale !== "ru" && <p className="text-tx-mute mt-2 text-sm">{t("readInRu")}</p>}

        <div lang="ru" className="mt-8">
          {blocks.map((block) =>
            block.heading ? (
              <h2 key={block.text} className="mt-8 text-base font-semibold">
                {block.text}
              </h2>
            ) : (
              <p key={block.text} className="text-tx-mute mt-3 text-sm leading-relaxed">
                {block.text}
              </p>
            ),
          )}
        </div>

        <Link
          href={pathFor(locale, "/register")}
          className="text-primary-ink mt-10 inline-block text-sm"
        >
          {t("back")}
        </Link>
      </main>
    </PageFrame>
  );
}
