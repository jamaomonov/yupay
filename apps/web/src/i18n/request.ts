import enCommon from "@yupay/i18n/locales/en/common.json";
import enWeb from "@yupay/i18n/locales/en/web.json";
import ruCommon from "@yupay/i18n/locales/ru/common.json";
import ruWeb from "@yupay/i18n/locales/ru/web.json";
import uzCommon from "@yupay/i18n/locales/uz/common.json";
import uzWeb from "@yupay/i18n/locales/uz/web.json";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

const CATALOGS = {
  ru: { common: ruCommon, web: ruWeb },
  en: { common: enCommon, web: enWeb },
  uz: { common: uzCommon, web: uzWeb },
} as const;

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  return { locale, messages: CATALOGS[locale] };
});
