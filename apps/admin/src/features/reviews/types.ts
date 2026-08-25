export interface AdminReview {
  id: string;
  brand_id: string;
  user_id: string | null;
  order_id: string;
  rating: number;
  body: string | null;
  status: string;
  report_count: number;
  created_at: string;
  /** Resolved brand. `null` only when the brand row is gone — a state the
   *  queue must still show, since it is the page that cleans up. */
  brand_slug: string | null;
  brand_name: string | null;
  brand_logo_url: string | null;
  /** The signed-in author's display name, or their login email when unset.
   *  `null` for a guest — read `guest_email` instead. Exactly one of the two
   *  is set, which is what lets the row label the author honestly. */
  user_name: string | null;
  guest_email: string | null;
}

export interface AdminReviewList {
  items: AdminReview[];
  total: number;
}

/** Per-brand rollup behind the by-brand block. Aggregated server-side: the
 *  queue is capped, so counting on the client would describe a slice of the
 *  reviews as if it were all of them. */
export interface AdminBrandReviewStats {
  brand_slug: string | null;
  brand_name: string | null;
  brand_logo_url: string | null;
  total: number;
  avg_rating: number;
  reported: number;
}

export interface AdminBrandReviewStatsList {
  items: AdminBrandReviewStats[];
}
