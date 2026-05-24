import { LOCALES } from "@yupay/i18n";

import type { MetadataRoute } from "next";

const SITE = "https://yupay.io";

export default function sitemap(): MetadataRoute.Sitemap {
  return LOCALES.map((locale) => ({
    url: locale === "ru" ? SITE : `${SITE}/${locale}`,
    lastModified: new Date(),
    changeFrequency: "daily",
    priority: 1.0,
  }));
}
