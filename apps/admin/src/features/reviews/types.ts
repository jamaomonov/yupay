export interface AdminReview {
  id: string;
  brand_id: string;
  user_id: string;
  order_id: string;
  rating: number;
  body: string | null;
  status: string;
  report_count: number;
  created_at: string;
}

export interface AdminReviewList {
  items: AdminReview[];
  total: number;
}
