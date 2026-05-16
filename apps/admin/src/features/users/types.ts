export interface TelegramLinkOut {
  tg_user_id: number;
  tg_username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  is_premium: boolean;
  last_seen_at: string;
}

export interface UserAdminOut {
  id: string;
  email: string | null;
  locale: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  telegram_link: TelegramLinkOut | null;
}

export interface UserAdminListOut {
  items: UserAdminOut[];
  total: number;
}
