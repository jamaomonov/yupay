/**
 * JSON-LD builders for blog pages. Offer stays off the article — the live
 * buy card / brand page owns the price.
 */

import { localeUrl } from "./seo";

import type { BlogPostDetail } from "./blog";

export function listStepsFromHtml(html: string): string[] {
  const match = /<ol\b[^>]*>([\s\S]*?)<\/ol>/i.exec(html);
  if (!match?.[1]) return [];
  return [...match[1].matchAll(/<li\b[^>]*>([\s\S]*?)<\/li>/gi)]
    .map((row) =>
      row[1]
        ?.replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter((step): step is string => Boolean(step));
}

export function articleJsonLd(post: BlogPostDetail, locale: string): Record<string, unknown> {
  const url = localeUrl(locale, `/blog/${post.slug}`);
  const type = post.kind === "guide" ? "Article" : "NewsArticle";
  const data: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": type,
    headline: post.title,
    description: post.excerpt,
    dateModified: post.updated_at,
    datePublished: post.published_at ?? post.updated_at,
    mainEntityOfPage: url,
    about: {
      "@type": "Brand",
      name: post.primary_brand.name,
      url: localeUrl(locale, `/store/${post.primary_brand.slug}`),
    },
  };
  if (post.cover_image_url) data.image = post.cover_image_url;
  return data;
}

export function howToJsonLd(post: BlogPostDetail, locale: string): Record<string, unknown> | null {
  const steps = listStepsFromHtml(post.body_html);
  if (post.kind !== "guide" || steps.length < 2) return null;
  return {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: post.title,
    description: post.excerpt,
    url: localeUrl(locale, `/blog/${post.slug}`),
    step: steps.map((text, i) => ({
      "@type": "HowToStep",
      position: i + 1,
      text,
    })),
  };
}

export function faqJsonLd(post: BlogPostDetail): Record<string, unknown> | null {
  if (post.faqs.length === 0) return null;
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: post.faqs.map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: { "@type": "Answer", text: faq.answer },
    })),
  };
}

export function breadcrumbJsonLd(
  locale: string,
  crumbs: { name: string; path: string }[],
): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((crumb, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: crumb.name,
      item: localeUrl(locale, crumb.path),
    })),
  };
}
