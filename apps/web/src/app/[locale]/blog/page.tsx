import Link from "next/link";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { BlogPostCard } from "@/components/blog/BlogPostCard";
import { buttonStyles } from "@/lib/button";
import { routing } from "@/i18n/routing";
import { listPublishedPosts } from "@/lib/blog";
import { alternates, GEO_META, localeUrl, ROBOTS, ogLocale, pathFor, truncate } from "@/lib/seo";

export const revalidate = 300;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.blog");
  const title = t("title");
  const description = truncate(t("description"));
  return {
    title: { absolute: `${title} · YuPay` },
    description,
    alternates: alternates(locale, "/blog"),
    other: GEO_META,
    robots: ROBOTS,
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title,
      description,
      url: localeUrl(locale, "/blog"),
      ...ogLocale(locale),
    },
  };
}

export default async function BlogIndexPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ cursor?: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations("web.blog");
  const cursor = (await searchParams).cursor;
  const page = await listPublishedPosts(locale, cursor ? { cursor } : undefined).catch(() => ({
    items: [],
    next_cursor: null,
  }));
  const grid =
    page.items.length === 1
      ? "mt-10 max-w-[400px]"
      : "mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3";

  return (
    <main id="main-content" className="mx-auto max-w-[1200px] px-6 pb-20 pt-28 sm:px-10">
      <h1 className="font-display text-3xl font-bold tracking-[-0.03em] sm:text-4xl">
        {t("title")}
      </h1>
      <p className="text-tx-mute mt-3 max-w-[640px] text-[16px] leading-relaxed">
        {t("description")}
      </p>
      {page.items.length === 0 ? (
        <div className="mt-10 flex max-w-[480px] flex-col gap-4">
          <p className="text-tx-mute">{t("empty")}</p>
          <p className="text-tx-dim text-sm">{t("emptyHint")}</p>
          <div className="flex flex-wrap gap-3">
            <Link href={pathFor(locale, "/store")} className={buttonStyles({ size: "md" })}>
              {t("emptyCta")}
            </Link>
            {locale !== "ru" ? (
              <Link href="/blog" className={buttonStyles({ variant: "ghost", size: "md" })}>
                {t("emptyRu")}
              </Link>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <div className={grid}>
            {page.items.map((post) => (
              <BlogPostCard key={post.id} post={post} locale={locale} />
            ))}
          </div>
          {page.next_cursor ? (
            <Link
              href={`${pathFor(locale, "/blog")}?cursor=${encodeURIComponent(page.next_cursor)}`}
              className="text-primary mt-8 inline-flex text-sm font-semibold"
            >
              {t("more")}
            </Link>
          ) : null}
        </>
      )}
    </main>
  );
}
