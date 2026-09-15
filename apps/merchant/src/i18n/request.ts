import enCommon from "@yupay/i18n/locales/en/common.json";
import enMerchant from "@yupay/i18n/locales/en/merchant.json";
import ruCommon from "@yupay/i18n/locales/ru/common.json";
import ruMerchant from "@yupay/i18n/locales/ru/merchant.json";
import uzCommon from "@yupay/i18n/locales/uz/common.json";
import uzMerchant from "@yupay/i18n/locales/uz/merchant.json";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

const CATALOGS = {
  ru: { common: ruCommon, merchant: ruMerchant },
  en: { common: enCommon, merchant: enMerchant },
  uz: { common: uzCommon, merchant: uzMerchant },
} as const;

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  return { locale, messages: CATALOGS[locale] };
});
