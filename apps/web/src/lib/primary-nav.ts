import { navSectionActive } from "@/lib/locale-href";
import { pathFor } from "@/lib/seo";

/** A header link: the `web.nav` key of its label and where it goes. */
export interface NavLink {
  key: "steam" | "skins" | "store" | "blog";
  href: string;
}

/**
 * The header's sections, most-wanted first: Steam top-up (most visitors come for it),
 * CS2 skins (while the section is on), the whole catalogue, the blog. Shared by the
 * desktop bar and the mobile sheet so the two never drift.
 */
export function primaryNavLinks(locale: string, skins: boolean): NavLink[] {
  return [
    { key: "steam" as const, href: pathFor(locale, "/store/steam") },
    ...(skins ? [{ key: "skins" as const, href: pathFor(locale, "/skins") }] : []),
    { key: "store" as const, href: pathFor(locale, "/store") },
    { key: "blog" as const, href: pathFor(locale, "/blog") },
  ];
}

/**
 * The one link to mark current: the longest matching section, so the Steam page
 * lights "Пополнить Steam" rather than both it and the catalogue it sits under.
 */
export function activeNavHref(pathname: string, links: NavLink[]): string | undefined {
  return links
    .filter((l) => navSectionActive(pathname, l.href))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
}
