/** Admin DTOs for `/api/v1/admin/blog`. Hand-written until OpenAPI settles. */

import adminRu from "@yupay/i18n/locales/ru/admin.json";

export const T = adminRu.blog;

export type Locale = "ru" | "en" | "uz";
export type PostKind = "guide" | "news" | "update" | "event";
export type PostStatus = "draft" | "scheduled" | "published" | "archived";

export const LOCALES: Locale[] = ["ru", "en", "uz"];
export const KINDS: PostKind[] = ["guide", "news", "update", "event"];

export interface Translation {
  locale: Locale;
  slug: string;
  title: string;
  excerpt: string;
  body_html: string;
  seo_title: string | null;
  seo_description: string | null;
}

export interface AdminPost {
  id: string;
  kind: PostKind;
  status: PostStatus;
  primary_brand_id: string;
  show_buy_card: boolean;
  pin_on_brand: boolean;
  cover_image_url: string | null;
  event_starts_at: string | null;
  event_ends_at: string | null;
  published_at: string | null;
  scheduled_for: string | null;
  created_at: string;
  updated_at: string;
  translations: Translation[];
  related_brand_ids: string[];
  faqs: Faq[];
}

export interface Faq {
  locale: Locale;
  sort_order: number;
  question: string;
  answer: string;
}

export interface AdminPostList {
  items: AdminPost[];
  total: number;
}

export interface PostWriteBody {
  kind: PostKind;
  primary_brand_id: string;
  show_buy_card: boolean;
  pin_on_brand: boolean;
  cover_image_url: string | null;
  event_starts_at: string | null;
  event_ends_at: string | null;
  translations: Translation[];
  faqs: Faq[];
}

export function idemHeaders(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
}
