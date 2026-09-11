import { apiGet, apiPatch, apiPost, newIdempotencyKey } from "./api";

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

export function getBrandReviews(slug: string, cursor?: string): Promise<ReviewPage> {
  const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiGet<ReviewPage>(`/api/v1/reviews/brands/${encodeURIComponent(slug)}${q}`, true);
}

export function submitReview(body: {
  order_id: string;
  brand_slug: string;
  rating: number;
  body?: string;
}): Promise<Review> {
  return apiPost<Review>("/api/v1/reviews", body, {
    idempotencyKey: newIdempotencyKey("review"),
  });
}

export function amendReview(reviewId: string, body: string): Promise<Review> {
  return apiPatch<Review>(
    `/api/v1/reviews/${encodeURIComponent(reviewId)}`,
    { body },
    { idempotencyKey: newIdempotencyKey("review-amend") },
  );
}

export interface PendingAsk {
  order_id: string;
  brand_slug: string;
  brand_name: string;
  delivered_at: string;
}

export async function getPendingAsk(): Promise<PendingAsk | null> {
  const row = await apiGet<PendingAsk | null>("/api/v1/reviews/pending-ask");
  return row;
}

export function getMyReviews(): Promise<{ items: OwnReview[] }> {
  return apiGet<{ items: OwnReview[] }>("/api/v1/reviews/mine");
}
