import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import {
  getBrandDetail,
  getBrandSlugs,
  getProductDetail,
  type LocaleMap,
  type ProductDetail,
} from "@/lib/catalog";
import {
  alternates,
  firstNonEmpty,
  formatUzs,
  GEO_META,
  localeUrl,
  pathFor,
  ROBOTS,
  ogLocale,
  truncate,
} from "@/lib/seo";

const CURRENCY = "UZS";

/** Pick a locale's string from a LocaleMap (ru fallback, then first value). */
function pick(m: LocaleMap | null | undefined, locale: string): string | null {
  if (!m) return null;
  return m[locale] ?? m.ru ?? Object.values(m)[0] ?? null;
}

/** Numbered steps out of an instructions blob, for the HowTo schema. Matches
 *  "1. …" runs whether they're on separate lines or inline. */
function parseSteps(instructions: string): string[] {
  const matches = instructions.match(/\d+\.\s+.+?(?=\s*\d+\.\s|$)/gs);
  return (matches ?? [])
    .map((s) =>
      s
        .replace(/^\d+\.\s+/, "")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter((s) => s.length > 0);
}

/** The account identifier's "where to find" help text, from the first product
 *  field that carries it (player id / login). */
function whereToFind(products: (ProductDetail | null)[], locale: string): string | null {
  for (const p of products) {
    const help = p?.required_fields[0]?.help_text;
    const text = pick(help, locale);
    if (text) return text;
  }
  return null;
}

export async function generateStaticParams() {
  return (await getBrandSlugs()).map((brandSlug) => ({ brandSlug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}): Promise<Metadata> {
  const { locale, brandSlug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const brand = await getBrandDetail(brandSlug, locale);
  if (!brand) return {};
  const t = await getTranslations("web.store");
  const title = t("howToMetaTitle", { name: brand.name });
  const description = truncate(t("howToMetaDescription", { name: brand.name }));
  const path = `/store/${brand.slug}/how-to`;
  return {
    title: { absolute: title },
    description,
    alternates: alternates(locale, path),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "article",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, path),
      images: brand.hero_image_url ? [{ url: brand.hero_image_url }] : undefined,
      ...ogLocale(locale),
    },
  };
}

export default async function HowToPage({
  params,
}: {
  params: Promise<{ locale: string; brandSlug: string }>;
}) {
  const { locale, brandSlug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  const brand = await getBrandDetail(brandSlug, locale, CURRENCY);
  if (!brand) notFound();
  const t = await getTranslations("web.store");
  const tn = await getTranslations("web.nav");

  const products = await Promise.all(
    (brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY)),
  );

  const title = t("howToTitle", { name: brand.name });
  const intro = firstNonEmpty(brand.short_description, brand.description);
  const instructions = brand.instructions ?? null;
  const steps = instructions ? parseSteps(instructions) : [];
  const findId = whereToFind(products, locale);
  const faqs = brand.faqs ?? [];
  const priced = products.filter((p): p is ProductDetail => p !== null && p.skus.length > 0);
  const moneyPath = `/store/${brand.slug}`;

  // Structured data: a HowTo (when we could split steps) + FAQPage + breadcrumb.
  const howToLd =
    steps.length >= 2
      ? {
          "@context": "https://schema.org",
          "@type": "HowTo",
          name: title,
          description: intro,
          step: steps.map((text, i) => ({ "@type": "HowToStep", position: i + 1, text })),
        }
      : undefined;
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
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: t("breadcrumbHome"), item: localeUrl(locale) },
      {
        "@type": "ListItem",
        position: 2,
        name: t("breadcrumbStore"),
        item: localeUrl(locale, "/store"),
      },
      { "@type": "ListItem", position: 3, name: brand.name, item: localeUrl(locale, moneyPath) },
      {
        "@type": "ListItem",
        position: 4,
        name: t("breadcrumbHowTo"),
        item: localeUrl(locale, `${moneyPath}/how-to`),
      },
    ],
  };

  return (
    <main className="relative min-h-screen pb-28 pt-[120px]">
      {howToLd && <JsonLd data={howToLd} />}
      {faqLd && <JsonLd data={faqLd} />}
      <JsonLd data={breadcrumbLd} />

      <article className="mx-auto max-w-[820px] px-6 sm:px-10">
        <nav
          aria-label={tn("breadcrumbLabel")}
          className="text-tx-dim mb-6 flex flex-wrap items-center gap-x-1.5 font-mono text-[11px]"
        >
          <Link
            href={pathFor(locale)}
            className="hover:text-tx-mute inline-flex items-center py-1.5"
          >
            {t("breadcrumbHome")}
          </Link>
          <ChevronRight size={12} />
          <Link
            href={pathFor(locale, "/store")}
            className="hover:text-tx-mute inline-flex items-center py-1.5"
          >
            {t("breadcrumbStore")}
          </Link>
          <ChevronRight size={12} />
          <Link
            href={pathFor(locale, moneyPath)}
            className="hover:text-tx-mute inline-flex items-center py-1.5"
          >
            {brand.name}
          </Link>
          <ChevronRight size={12} />
          <span className="text-tx-mute">{t("breadcrumbHowTo")}</span>
        </nav>

        <h1 className="font-display text-[clamp(1.8rem,4vw,2.6rem)] font-bold leading-tight tracking-[-0.02em]">
          {title}
        </h1>
        {intro && <p className="text-tx-mute mt-4 text-[15px] leading-relaxed">{intro}</p>}

        {/* Step-by-step */}
        {instructions && (
          <section className="mt-12">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {t("howToStepsTitle")}
            </h2>
            {steps.length >= 2 ? (
              <ol className="mt-5 space-y-4">
                {steps.map((s, i) => (
                  <li key={i} className="flex gap-4">
                    <span className="bg-primary/10 text-primary flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[13px] font-bold">
                      {i + 1}
                    </span>
                    <span className="text-tx-mute pt-1 text-[15px] leading-relaxed">{s}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-tx-mute mt-4 whitespace-pre-line text-[15px] leading-relaxed">
                {instructions}
              </p>
            )}
          </section>
        )}

        {/* Where to find the ID / login */}
        {findId && (
          <section className="mt-12">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {t("whereToFind")}
            </h2>
            <p className="text-tx-mute mt-4 whitespace-pre-line text-[15px] leading-relaxed">
              {findId}
            </p>
          </section>
        )}

        {/* Prices */}
        {priced.length > 0 && (
          <section className="mt-12">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
              {t("pricesTitle")}
            </h2>
            <div className="mt-5 space-y-6">
              {priced.map((p) => (
                <div key={p.id}>
                  {products.length > 1 && (
                    <div className="text-tx-mute mb-2 text-sm font-semibold">{p.name}</div>
                  )}
                  <dl className="border-border divide-border/70 rounded-btn divide-y overflow-hidden border">
                    {p.skus.map((s) => {
                      const name = s.variable_amount
                        ? `${s.min_amount_usd ? `$${String(Number(s.min_amount_usd))}` : "$1"}–${s.max_amount_usd ? `$${String(Number(s.max_amount_usd))}` : "$300"}`
                        : (s.denomination ?? s.sku_code);
                      const price = s.display_price
                        ? formatUzs(locale, Math.round(Number(s.display_price.amount)))
                        : null;
                      return (
                        <div
                          key={s.id}
                          className="flex items-center justify-between gap-4 px-4 py-2.5 text-[14px]"
                        >
                          <dt className="text-tx-mute">{name}</dt>
                          {price && <dd className="font-mono font-semibold">{price}</dd>}
                        </div>
                      );
                    })}
                  </dl>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* FAQ */}
        {faqs.length > 0 && (
          <section className="mt-12">
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("faqTitle")}</h2>
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

        {/* CTA back to the money page */}
        <div className="border-border bg-card mt-14 flex flex-col items-start gap-4 rounded-xl border bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--bg)))] p-7 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="font-display text-lg font-bold tracking-[-0.02em]">{brand.name}</div>
            {intro && <div className="text-tx-mute mt-1 max-w-[46ch] text-[13px]">{intro}</div>}
          </div>
          <Link
            href={pathFor(locale, moneyPath)}
            className="bg-primary text-primary-foreground rounded-btn inline-flex shrink-0 items-center gap-2 px-6 py-3 text-[15px] font-bold transition hover:brightness-110"
          >
            {t("guideCtaButton", { name: brand.name })}
            <ChevronRight size={18} />
          </Link>
        </div>
      </article>
    </main>
  );
}
