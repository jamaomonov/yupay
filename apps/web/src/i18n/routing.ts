import { DEFAULT_LOCALE, LOCALES } from "@yupay/i18n";
import { defineRouting } from "next-intl/routing";


export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: "as-needed",
});

export type AppLocale = (typeof routing.locales)[number];
