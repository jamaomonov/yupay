import { type AppLocale } from "@/i18n/routing";
import { pathFor } from "./seo";

/**
 * Locale-switch href for the current storefront path.
 *
 * A blog article is per-locale: if the target language has no row, send the
 * reader to that locale's blog index instead of a 404 on the same slug.
 */
export function hrefForLocale(
  next: AppLocale,
  pathname: string,
  blogSlugs?: Record<string, string> | null,
): string {
  const stripped = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
  const article = /^\/blog\/([^/]+)$/.exec(stripped);
  if (article !== null) {
    const slug = blogSlugs?.[next];
    if (typeof slug === "string" && slug.length > 0) {
      return pathFor(next, `/blog/${slug}`);
    }
    return pathFor(next, "/blog");
  }
  return pathFor(next, stripped === "/" ? "" : stripped);
}

/** True when this nav href is the current section (prefix match on children). */
export function navSectionActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
