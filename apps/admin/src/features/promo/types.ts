/** Admin DTOs for the promo module. Mirrors `promo/schemas.py`. */

export interface PromoRedemptionOut {
  user_id: string;
  display_name: string | null;
  photo_url: string | null;
  tg_username: string | null;
  email: string | null;
  redeemed_at: string;
}

export interface PromoRedemptionListOut {
  items: PromoRedemptionOut[];
  total: number;
}
