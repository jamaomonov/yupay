import { DEFAULT_LOCALE, LOCALES } from "@yupay/i18n";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: "as-needed",
  // A URL means one language, for everybody.
  //
  // With detection on, `/store/steam` — the URL we publish as the Russian page
  // in hreflang and as its own canonical — answered an English browser with a
  // redirect to `/en/store/steam`. So the canonical served content to some
  // visitors and a redirect to others, and someone arriving from a Russian
  // search result was bounced to a page that was never in the results. Google's
  // own guidance is to let hreflang do this and offer a switch, not to redirect
  // on Accept-Language.
  //
  // The cost is small here because the language switcher is a set of links: a
  // visitor's choice lives in the URL they end up on, so it survives in history
  // and bookmarks. What is lost is the bare-domain case — someone who once
  // switched to Uzbek and later types yupay.uz now lands on Russian and picks
  // again.
  localeDetection: false,

  // Stop writing NEXT_LOCALE at all. next-intl set it on every page response,
  // and Cloudflare will not cache a response carrying Set-Cookie — so every ad
  // click paid for an origin render of a page that is identical for every
  // anonymous visitor. Nothing read the cookie: detection is off above, and a
  // grep across apps/ and packages/ finds no consumer. (In older next-intl this
  // was bundled into `localeDetection`; since v4 it is its own flag.)
  localeCookie: false,
});

export type AppLocale = (typeof routing.locales)[number];
