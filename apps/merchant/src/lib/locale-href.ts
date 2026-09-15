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
/**
 * A root-relative link, honouring `as-needed`.
 *
 * Every internal link in the app goes through this rather than being written
 * as `` `/${locale}/x` ``, and it fixes two things that literal was quietly
 * costing us. The default locale has **no** segment, so `/ru/cabinet/orders`
 * was a 308 to `/cabinet/orders` — a redirect on every click in the cabinet.
 * And because `usePathname()` returns the browser's path, which after that
 * redirect has no prefix, `pathname === "/ru/cabinet/orders"` never matched:
 * the sidebar highlighted nothing at all for anyone browsing in Russian,
 * which is everyone.
 */
export function pathFor(locale: string, path: string): string {
  const prefix = locale === routing.defaultLocale ? "" : `/${locale}`;
  const rest = path === "/" ? "" : path;
  return `${prefix}${rest}` === "" ? "/" : `${prefix}${rest}`;
}

/**
 * Strip a locale segment, so two paths can be compared for "same page".
 *
 * `usePathname()` gives the browser's path and a link may carry a prefix or
 * not; normalising both ends is what makes an active-state check survive
 * either.
 */
export function withoutLocale(pathname: string): string {
  const [, first = "", ...rest] = pathname.split("/");
  const tail = isLocale(first) ? rest : [first, ...rest];
  const path = tail.filter((part) => part !== "").join("/");
  return path === "" ? "/" : `/${path}`;
}

export function hrefForLocale(next: AppLocale, pathname: string): string {
  return pathFor(next, withoutLocale(pathname));
}
