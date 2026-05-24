import en from "@yupay/i18n/locales/en/common.json";
import ru from "@yupay/i18n/locales/ru/common.json";
import uz from "@yupay/i18n/locales/uz/common.json";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { routing } from "./routing";

const CATALOGS = { ru, en, uz } as const;

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;

  return {
    locale,
    messages: {
      common: CATALOGS[locale],
    },
  };
});
