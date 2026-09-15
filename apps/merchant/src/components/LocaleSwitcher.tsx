"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { routing, type AppLocale } from "@/i18n/routing";
import { hrefForLocale } from "@/lib/locale-href";

/**
 * Three links, not a dropdown.
 *
 * The storefront's switcher is a menu because it carries flags and autonyms
 * and sits in a crowded header. Here there are three two-letter codes: a menu
 * would hide them behind a click, need outside-click and Escape handling, and
 * stop working without JS — all to save the width of one word. Changing
 * language is a navigation, and a row of links says exactly that.
 *
 * Until this existed the only way to read the cabinet in English was to type
 * the locale into the address bar.
 */
export function LocaleSwitcher({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  const current = useLocale() as AppLocale;
  const t = useTranslations("merchant.common");

  return (
    <nav
      aria-label={t("localeSwitch")}
      className={`border-border rounded-btn flex items-center border p-0.5 ${className}`}
    >
      {routing.locales.map((locale) => {
        const active = locale === current;
        return (
          <Link
            key={locale}
            href={hrefForLocale(locale, pathname)}
            hrefLang={locale}
            aria-current={active ? "true" : undefined}
            className={`rounded-lg px-2 py-1 text-[11px] font-bold uppercase tracking-wider transition ${
              active
                ? "bg-card-2 text-foreground"
                : "text-tx-dim hover:text-foreground hover:bg-card-2/60"
            }`}
          >
            {locale}
          </Link>
        );
      })}
    </nav>
  );
}
