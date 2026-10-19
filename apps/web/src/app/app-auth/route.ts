import en from "@yupay/i18n/locales/en/web.json";
import ru from "@yupay/i18n/locales/ru/web.json";
import uz from "@yupay/i18n/locales/uz/web.json";

import { appAuthHtml } from "@/lib/app-auth-page";

// The same page for everyone; the provider IDs are build-time public values.
export const dynamic = "force-static";

const HTML = appAuthHtml({
  googleClientId: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "",
  telegramBotId: process.env.NEXT_PUBLIC_TELEGRAM_BOT_ID ?? "",
  text: Object.fromEntries(
    Object.entries({ ru, en, uz }).map(([locale, messages]) => [
      locale,
      { wait: messages.auth.appBounce, failed: messages.auth.appBounceFailed },
    ]),
  ),
});

/** The mobile app's Google and Telegram sign-in bounce: see `lib/app-auth-page.ts`. */
export function GET(): Response {
  return new Response(HTML, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}
