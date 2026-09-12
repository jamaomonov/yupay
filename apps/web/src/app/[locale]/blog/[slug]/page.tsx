import { ChevronRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { ArticleActions } from "@/components/blog/ArticleActions";
import { ArticleBody } from "@/components/blog/ArticleBody";
import { BuyCard } from "@/components/blog/BuyCard";
import { EngagementStats } from "@/components/blog/EngagementStats";
import { JsonLd } from "@/components/JsonLd";
import { routing } from "@/i18n/routing";
import { eventChip, getPublishedBlogEntries, getPublishedPost, type PostKind } from "@/lib/blog";
import {
  articleJsonLd,
  breadcrumbJsonLd,
  faqJsonLd,
  howToJsonLd,
} from "@/lib/blog-jsonld";
import { isOptimizable } from "@/lib/image";
import {
  blogAlternates,
  firstNonEmpty,
  GEO_META,
  localeUrl,
  ogLocale,
  pathFor,
  ROBOTS,
  truncate,
} from "@/lib/seo";

export const revalidate = 300;

const KIND_KEY: Record<PostKind, "kind.guide" | "kind.news" | "kind.update" | "kind.event"> = {
  guide: "kind.guide",
  news: "kind.news",
  update: "kind.update",
  event: "kind.event",
};

export async function generateStaticParams() {
  const entries = await getPublishedBlogEntries();
  return [...new Set(entries.map((row) => row.slug))].map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const post = await getPublishedPost(slug, locale);
  if (!post) return {};
  const title = firstNonEmpty(post.seo_title, post.title) ?? post.title;
  const description = truncate(firstNonEmpty(post.seo_description, post.excerpt) ?? post.title);
  return {
    title: { absolute: title },
    description,
    alternates: blogAlternates(locale, post.locale_slugs),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "article",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, `/blog/${post.slug}`),
      images: post.cover_image_url ? [{ url: post.cover_image_url }] : undefined,
      ...ogLocale(locale),
    },
  };
}

export default async function BlogArticlePage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const post = await getPublishedPost(slug, locale);
  if (!post) notFound();

  const t = await getTranslations("web.blog");
  const tn = await getTranslations("web.nav");
  const chip = eventChip(post);
  const updated = new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
    new Date(post.updated_at),
  );
  const howTo = howToJsonLd(post, locale);
  const faq = faqJsonLd(post);

  return (
    <main className="mx-auto max-w-[1200px] px-6 pb-20 pt-28 sm:px-10">
      <JsonLd data={articleJsonLd(post, locale)} />
      {howTo ? <JsonLd data={howTo} /> : null}
      {faq ? <JsonLd data={faq} /> : null}
      <JsonLd
        data={breadcrumbJsonLd(locale, [
          { name: tn("blog"), path: "/blog" },
          { name: post.title, path: `/blog/${post.slug}` },
        ])}
      />

      <nav aria-label={tn("breadcrumbLabel")} className="text-tx-mute mb-6 flex flex-wrap items-center gap-1 text-sm">
        <Link href={pathFor(locale, "/blog")} className="hover:text-foreground">
          {tn("blog")}
        </Link>
        <ChevronRight size={14} className="text-tx-dim" />
        <span className="text-foreground">{post.title}</span>
      </nav>

      <article className="mx-auto max-w-[720px]">
        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em]">
          <span className="text-primary">{t(KIND_KEY[post.kind])}</span>
          {chip === "live" ? <span className="text-primary">{t("live")}</span> : null}
          {chip === "ended" ? <span className="text-tx-dim">{t("ended")}</span> : null}
        </div>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.03em] sm:text-4xl">
          {post.title}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p className="text-tx-dim font-mono text-[12px]">{t("updated", { date: updated })}</p>
          <EngagementStats likes={post.like_count} views={post.view_count} />
        </div>
        {post.cover_image_url ? (
          <div className="bg-card-2 relative mt-6 aspect-video overflow-hidden rounded-2xl">
            <Image
              src={post.cover_image_url}
              alt=""
              fill
              unoptimized={!isOptimizable(post.cover_image_url)}
              sizes="720px"
              className="object-cover"
              priority
            />
          </div>
        ) : null}
        <div className="mt-8">
          <ArticleBody html={post.body_html} />
        </div>
        {post.faqs.length > 0 ? (
          <section className="mt-12">
            <h2 className="font-display text-xl font-semibold tracking-[-0.02em]">{t("faqs")}</h2>
            <div className="mt-4 flex flex-col">
              {post.faqs.map((item) => (
                <details
                  key={`${item.sort_order.toString()}-${item.question}`}
                  className="border-border/70 group border-b"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between py-3 text-[15px] font-semibold">
                    {item.question}
                    <ChevronRight size={16} className="text-tx-dim shrink-0 transition group-open:rotate-90" />
                  </summary>
                  <p className="text-tx-mute -mt-1 pb-4 pr-8 text-[15px] leading-relaxed">{item.answer}</p>
                </details>
              ))}
            </div>
          </section>
        ) : null}
        <ArticleActions
          slug={post.slug}
          locale={locale}
          title={post.title}
          initialLikes={post.like_count}
        />
        {post.show_buy_card ? <BuyCard brandSlug={post.primary_brand.slug} locale={locale} /> : null}
      </article>
    </main>
  );
}
