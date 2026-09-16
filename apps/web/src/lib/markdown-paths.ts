/**
 * Which pages answer `Accept: text/markdown`, in one place.
 *
 * The middleware rewrites those requests to `/md…`, and the HTML head of the
 * same pages advertises the Markdown view with
 * `<link rel="alternate" type="text/markdown">`. Those two have to agree: a
 * page that advertises a view the middleware will not serve sends an agent to
 * a 404, and a page that serves one without advertising it is only findable
 * through `llms.txt`.
 *
 * Kept free of imports so the edge middleware can pull it in unchanged.
 */

/** Does `pathname` (locale prefix optional) have a Markdown view? */
export function supportsMarkdown(pathname: string): boolean {
  const p = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
  return (
    p === "/" ||
    p === "/store" ||
    p === "/blog" ||
    /^\/store\/[^/]+$/.test(p) ||
    /^\/store\/[^/]+\/how-to$/.test(p) ||
    /^\/blog\/[^/]+$/.test(p)
  );
}

/** The Markdown URL for a locale-less `path`, or `null` when it has none. */
export function markdownUrl(site: string, locale: string, path = ""): string | null {
  const localized = locale === "ru" ? path : `/${locale}${path}`;
  if (!supportsMarkdown(localized || "/")) return null;
  return `${site}/md${localized}`;
}
