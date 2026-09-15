"use client";

import { useTranslations } from "next-intl";

/**
 * The first tab stop on a page, and invisible until it is one.
 *
 * Measured before this existed: 34 Tab presses to reach the content of a docs
 * page, because the sidebar lists every guide, every endpoint and every
 * schema; the cabinet repeats its whole sidebar on every screen. Landmarks
 * solve this for a screen reader and do nothing at all for a sighted
 * keyboard-only or switch user, who pays the stops on every navigation.
 *
 * `sr-only` until focused, which is the whole convention: it costs a sighted
 * mouse user nothing and is the first thing a keyboard user finds.
 */
export function SkipLink() {
  const t = useTranslations("merchant.common");
  return (
    <a
      href="#main"
      className="bg-primary text-primary-foreground rounded-btn sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold"
    >
      {t("skipToContent")}
    </a>
  );
}
