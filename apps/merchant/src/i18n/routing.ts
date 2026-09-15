import { DEFAULT_LOCALE, LOCALES } from "@yupay/i18n";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: "as-needed",
  // Both off, for the reasons apps/web works through at length and which apply
  // here for one of the same two: a URL means one language, so the landing's
  // canonical serves content to everybody rather than a redirect to some.
  //
  // The cookie half matters less here than on the storefront — a cabinet is
  // behind a login and not an ad click, so nothing is paying Cloudflare for an
  // origin render — but a flag nobody reads is still a flag that can only
  // surprise someone later.
  localeDetection: false,
  localeCookie: false,
});

export type AppLocale = (typeof routing.locales)[number];
