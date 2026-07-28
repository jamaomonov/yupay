import { apiGet } from "./api";
import { apiFetch } from "./client";

export interface Review {
  id: string;
  rating: number;
  body: string | null;
  author_name: string | null;
  created_at: string;
}

export interface ReviewStats {
  avg: number;
  count: number;
  dist: Record<string, number>;
}

export interface ReviewPage {
  items: Review[];
  next_cursor: string | null;
  stats: ReviewStats;
}

export interface OwnReview {
  id: string;
  order_id: string;
  brand_id: string;
  rating: number;
}

/** Server-side (RSC) fetch of a brand's published reviews + aggregate. */
export function getBrandReviews(
  slug: string,
  locale: string,
  cursor?: string,
): Promise<ReviewPage> {
  const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiGet<ReviewPage>(`/reviews/brands/${encodeURIComponent(slug)}${q}`, {
    locale,
    revalidate: 60,
    tags: ["reviews"],
  });
}

/** Client-side fetch of another page (used by the interactive "load more"). */
export function fetchMoreReviews(slug: string, cursor: string): Promise<ReviewPage> {
  return apiFetch<ReviewPage>(
    `/reviews/brands/${encodeURIComponent(slug)}?cursor=${encodeURIComponent(cursor)}`,
    { anonymous: true },
  );
}

export function submitReview(body: {
  order_id: string;
  brand_slug: string;
  rating: number;
  body?: string;
}): Promise<Review> {
  return apiFetch<Review>("/reviews", {
    method: "POST",
    body,
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export function getMyReviews(): Promise<{ items: OwnReview[] }> {
  return apiFetch<{ items: OwnReview[] }>("/reviews/mine");
}

export async function reportReview(reviewId: string, reason?: string): Promise<void> {
  await apiFetch(`/reviews/${reviewId}/report`, {
    method: "POST",
    body: { reason: reason ?? null },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}
