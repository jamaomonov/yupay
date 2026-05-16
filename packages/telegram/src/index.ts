/**
 * Client-side Telegram types. The server is responsible for validating `initData` —
 * never trust anything decoded from `initDataUnsafe` on the client for authorisation.
 */

export interface TelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
}

export interface TelegramWebAppInitDataUnsafe {
  query_id?: string;
  user?: TelegramUser;
  auth_date?: number;
  hash?: string;
  start_param?: string;
}

/** Map a Telegram language code to one of our supported locales. */
export function mapTelegramLocale(
  code: string | undefined,
  fallback: "ru" | "en" | "uz" = "ru",
): "ru" | "en" | "uz" {
  if (!code) return fallback;
  const lc = code.toLowerCase();
  if (lc.startsWith("ru")) return "ru";
  if (lc.startsWith("en")) return "en";
  if (lc.startsWith("uz")) return "uz";
  return fallback;
}
