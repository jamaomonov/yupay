/**
 * Deep link that opens the YuPay storefront **Mini App** inside Telegram — the
 * `@yupayapp_bot` mini app, NOT the `@yupay_support` chat or the `@yupay_bot`
 * customer bot. This is the primary conversion target on mobile.
 *
 * NOTE: the path segment must match the Mini App short name configured in
 * BotFather (`/setdomain` + the mini app you registered). Common values:
 *   - `https://t.me/yupayapp_bot/app`     — a named "direct link" mini app
 *   - `https://t.me/yupayapp_bot?startapp` — a Main Mini App without a short name
 * Change this one constant once the BotFather short name is confirmed.
 */
export const TELEGRAM_MINIAPP_URL = "https://t.me/yupayapp_bot/app";
