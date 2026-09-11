export interface TelegramLinkOut {
  tg_user_id: number;
  tg_username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  is_premium: boolean;
  last_seen_at: string;
}

export interface SteamLinkOut {
  steam_id: number;
  persona_name: string | null;
  avatar_url: string | null;
}

export interface UserWalletBalanceOut {
  currency: string;
  balance: string;
}

export interface UserAdminOut {
  id: string;
  email: string | null;
  locale: string;
  display_currency: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  /** Set = the account is suspended. A timestamp rather than a flag so the
   *  admin can see since when without opening the audit trail. */
  banned_at: string | null;
  ban_reason: string | null;
  banned_by: string | null;
  telegram_link: TelegramLinkOut | null;
  steam_link: SteamLinkOut | null;
  wallet_balances: UserWalletBalanceOut[];
}

export interface UserAdminListOut {
  items: UserAdminOut[];
  total: number;
  /** Global user_wallet liability, not filtered by the current search. */
  wallet_totals: UserWalletBalanceOut[];
}

export type UserAdminSort =
  | "created_desc"
  | "created_asc"
  | "wallet_desc"
  | "wallet_asc"
  | "name_asc"
  | "name_desc";
