import { routing, type AppLocale } from "@/i18n/routing";

/** `true` when the first path segment is one of our locales. */
function isLocale(segment: string): segment is AppLocale {
  return (routing.locales as readonly string[]).includes(segment);
}

/**
 * The same page in another language.
 *
 * `localePrefix: "as-needed"` means the default locale has **no** segment at
 * all, so this is not a substitution — switching *to* the default has to
 * produce the bare path, and switching *from* it has to add a segment that was
 * never there. `/ru/cabinet` only 308-redirects to `/cabinet`, and making a
 * deliberate click cost a round trip is a waste we can simply not have.
 *
 * Every route in this app exists under all three locales with the same slugs,
 * so unlike the storefront there is no per-locale content to fall back from.
 */
export function hrefForLocale(next: AppLocale, pathname: string): string {
  const [, first = "", ...rest] = pathname.split("/");
  const tail = isLocale(first) ? rest : [first, ...rest].filter((part) => part !== "");
  const path = tail.join("/");
  const prefix = next === routing.defaultLocale ? "" : `/${next}`;
  return path === "" ? prefix || "/" : `${prefix}/${path}`;
}
