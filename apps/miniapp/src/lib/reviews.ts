import { apiGet, apiPost, newIdempotencyKey } from "./api";

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

export function getMyReviews(): Promise<{ items: OwnReview[] }> {
  return apiGet<{ items: OwnReview[] }>("/api/v1/reviews/mine");
}
