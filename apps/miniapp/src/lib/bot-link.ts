/**
 * Deep link to the bot.
 *
 * Lives here rather than inline in a page because more than one screen needs
 * it: the top-up screen offered "Открыть бота" when opened outside Telegram
 * while History and Settings showed the same warning banner with no way out.
 * Two copies of the env-var name is exactly how they drift apart.
 */
const BOT_USERNAME = (
  (import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined) ?? ""
).replace(/^@/, "");

export const BOT_LINK: string | null = BOT_USERNAME ? `https://t.me/${BOT_USERNAME}` : null;
