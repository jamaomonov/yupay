import { apiGet } from "./api";
import { apiFetch } from "./client";
import { mintGuestToken } from "./guest";

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

export interface ReviewEligibility {
  brand_slug: string | null;
  delivered: boolean;
  already_reviewed: boolean;
}

/** Mint a guest token for `email` and shape it into the headers `apiFetch`
 *  needs for a guest-authenticated call: `Authorization: Guest <token>` plus
 *  the `X-Guest-Email` the server cross-checks against the token's email hash. */
async function guestHeaders(email: string): Promise<Record<string, string>> {
  const token = await mintGuestToken(email);
  return { Authorization: `Guest ${token}`, "X-Guest-Email": email.trim().toLowerCase() };
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

export async function submitReview(
  body: { order_id: string; brand_slug: string; rating: number; body?: string },
  opts: { guestEmail?: string } = {},
): Promise<Review> {
  const extra = opts.guestEmail ? await guestHeaders(opts.guestEmail) : {};
  return apiFetch<Review>("/reviews", {
    method: "POST",
    body,
    anonymous: Boolean(opts.guestEmail),
    headers: { "Idempotency-Key": crypto.randomUUID(), ...extra },
  });
}

/** Eligibility to review an order (delivered + not already reviewed) for its
 *  brand. Pass `guestEmail` to check as a guest (mints a guest token and
 *  authenticates with `Guest <token>` + `X-Guest-Email` instead of Bearer). */
export async function getReviewEligibility(
  orderId: string,
  opts: { guestEmail?: string } = {},
): Promise<ReviewEligibility> {
  const extra = opts.guestEmail ? await guestHeaders(opts.guestEmail) : {};
  return apiFetch<ReviewEligibility>(
    `/reviews/eligibility?order_id=${encodeURIComponent(orderId)}`,
    { anonymous: Boolean(opts.guestEmail), headers: extra },
  );
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
