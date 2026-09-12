/**
 * Public blog reads. DTOs mirror ``modules/blog/schemas``. Fetches are tagged
 * ``blog`` and revalidate with the brand pages (300s).
 */

import { apiGet, apiGetOrNull } from "./api";

export type PostKind = "guide" | "news" | "update" | "event";

export interface BrandRef {
  slug: string;
  name: string;
}

export interface BlogFaq {
  locale: string;
  sort_order: number;
  question: string;
  answer: string;
}

export interface BlogListItem {
  id: string;
  slug: string;
  kind: PostKind;
  title: string;
  excerpt: string;
  cover_image_url: string | null;
  published_at: string | null;
  updated_at: string;
  primary_brand: BrandRef;
  event_starts_at: string | null;
  event_ends_at: string | null;
  pin_on_brand: boolean;
  like_count: number;
  view_count: number;
}

export interface BlogPostDetail extends BlogListItem {
  body_html: string;
  seo_title?: string | null;
  seo_description?: string | null;
  show_buy_card: boolean;
  related_brand_slugs: string[];
  faqs: BlogFaq[];
  locale_slugs: Record<string, string>;
}

export interface BlogListOut {
  items: BlogListItem[];
  next_cursor: string | null;
}

const REVALIDATE = 300;
const TAGS = ["blog"];

export function listPublishedPosts(
  locale: string,
  opts?: { brand?: string; kind?: PostKind; cursor?: string },
): Promise<BlogListOut> {
  const q = new URLSearchParams();
  if (opts?.brand) q.set("brand", opts.brand);
  if (opts?.kind) q.set("kind", opts.kind);
  if (opts?.cursor) q.set("cursor", opts.cursor);
  const suffix = q.size > 0 ? `?${q.toString()}` : "";
  return apiGet<BlogListOut>(`/blog${suffix}`, { locale, revalidate: REVALIDATE, tags: TAGS });
}

export function getPublishedPost(slug: string, locale: string): Promise<BlogPostDetail | null> {
  return apiGetOrNull<BlogPostDetail>(`/blog/${encodeURIComponent(slug)}`, {
    locale,
    revalidate: REVALIDATE,
    tags: TAGS,
  });
}

export function listBrandPosts(brandSlug: string, locale: string): Promise<BlogListItem[]> {
  return apiGet<{ items: BlogListItem[] }>(`/blog/by-brand/${encodeURIComponent(brandSlug)}`, {
    locale,
    revalidate: REVALIDATE,
    tags: TAGS,
  }).then((r) => r.items);
}

/** Slugs for generateStaticParams / sitemap. Empty if the API is down. */
export async function getPublishedBlogEntries(): Promise<
  { locale: string; slug: string; updated_at: string; id: string }[]
> {
  const locales = ["ru", "en", "uz"] as const;
  try {
    const pages = await Promise.all(locales.map((locale) => listAll(locale)));
    return pages.flat();
  } catch {
    return [];
  }
}

async function listAll(
  locale: string,
): Promise<{ locale: string; slug: string; updated_at: string; id: string }[]> {
  const out: { locale: string; slug: string; updated_at: string; id: string }[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 20; page += 1) {
    const batch = await listPublishedPosts(locale, cursor ? { cursor } : undefined);
    for (const item of batch.items) {
      out.push({ locale, slug: item.slug, updated_at: item.updated_at, id: item.id });
    }
    if (!batch.next_cursor) break;
    cursor = batch.next_cursor;
  }
  return out;
}

export function eventChip(
  item: Pick<BlogListItem, "kind" | "event_starts_at" | "event_ends_at">,
  nowMs = Date.now(),
): "live" | "ended" | null {
  if (item.kind !== "event" || !item.event_starts_at || !item.event_ends_at) return null;
  const start = Date.parse(item.event_starts_at);
  const end = Date.parse(item.event_ends_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  if (nowMs >= start && nowMs <= end) return "live";
  if (nowMs > end) return "ended";
  return null;
}
