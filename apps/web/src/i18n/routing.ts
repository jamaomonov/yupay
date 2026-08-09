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
  // again. next-intl bundles the cookie into this same flag, so that part is
  // not separable.
  localeDetection: false,
});

export type AppLocale = (typeof routing.locales)[number];
