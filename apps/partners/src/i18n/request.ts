import enCommon from "@yupay/i18n/locales/en/common.json";
import enPartners from "@yupay/i18n/locales/en/partners.json";
import ruCommon from "@yupay/i18n/locales/ru/common.json";
import ruPartners from "@yupay/i18n/locales/ru/partners.json";
import uzCommon from "@yupay/i18n/locales/uz/common.json";
import uzPartners from "@yupay/i18n/locales/uz/partners.json";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

const CATALOGS = {
  ru: { common: ruCommon, partners: ruPartners },
  en: { common: enCommon, partners: enPartners },
  uz: { common: uzCommon, partners: uzPartners },
} as const;

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  return { locale, messages: CATALOGS[locale] };
});
