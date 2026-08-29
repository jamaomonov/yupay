"use client";

import NextLink from "next/link";
import { useLocale } from "next-intl";

import { usePathname } from "@/i18n/navigation";
import { routing, type AppLocale } from "@/i18n/routing";

/**
 * Three links, not a dropdown.
 *
 * The storefront opens a flag menu, which suits a header that already has a
 * cart and an account in it. Here the whole bar is one line of monospaced
 * capitals, and `RU · EN · UZ` is shorter than the button that would open a
 * list of three. It also needs no JavaScript, survives with the page
 * prerendered, and is crawlable — the language a visitor picks lives in the
 * URL they land on.
 *
 * No flags. A flag names a country, and English is not the United Kingdom.
 *
 * `usePathname` from `@/i18n/navigation` gives the path without its locale
 * segment, and the prefix is rebuilt here rather than by that module's `Link`.
 * Passing `locale` to it always emits a prefix, so Russian came out as `/ru`,
 * which only 307-redirects to `/` — a round trip charged to every deliberate
 * click on the default language.
 */
export function LocaleSwitcher() {
  const pathname = usePathname();
  const current = useLocale() as AppLocale;

  const hrefFor = (loc: AppLocale): string =>
    loc === routing.defaultLocale ? pathname : `/${loc}${pathname === "/" ? "" : pathname}`;

  return (
    <nav aria-label="Language" className="flex items-center gap-2.5">
      {routing.locales.map((loc) => {
        const active = loc === current;
        return (
          <NextLink
            key={loc}
            href={hrefFor(loc)}
            hrefLang={loc}
            aria-current={active ? "true" : undefined}
            className={`-my-2 py-2 transition ${
              active ? "text-primary" : "text-tx-dim hover:text-foreground"
            }`}
          >
            {loc}
          </NextLink>
        );
      })}
    </nav>
  );
}
