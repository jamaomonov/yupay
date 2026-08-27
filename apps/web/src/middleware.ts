import { NextResponse, type NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

/** `/ru`, `/ru/anything` — the prefix next-intl strips for the default locale. */
const DEFAULT_PREFIX = new RegExp(`^/${routing.defaultLocale}(?=/|$)`);

/**
 * Pages we can serve as Markdown for agents (after stripping an optional
 * locale prefix): the home page, the store index, and any single brand page.
 */
function supportsMarkdown(pathname: string): boolean {
  const p = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
  return (
    p === "/" || p === "/store" || /^\/store\/[^/]+$/.test(p) || /^\/store\/[^/]+\/how-to$/.test(p)
  );
}

/**
 * Is this a React Server Component payload request rather than a document?
 *
 * Next marks client-side navigation and prefetch with an `RSC` header, and
 * carries a `_rsc` cache-buster in the query. Either is enough to identify it;
 * both are checked because a header can be stripped by an intermediary and the
 * query param can survive a redirect.
 */
function isFlightRequest(req: NextRequest): boolean {
  return req.headers.has("rsc") || req.nextUrl.searchParams.has("_rsc");
}

export default function middleware(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;
  const negotiable = supportsMarkdown(pathname);

  // Agent asked for Markdown on a supported page → serve the /md view; browsers
  // (Accept: text/html) fall through to the normal localized HTML.
  if (negotiable && (req.headers.get("accept") ?? "").includes("text/markdown")) {
    const url = req.nextUrl.clone();
    url.pathname = `/md${pathname === "/" ? "" : pathname}`;
    const res = NextResponse.rewrite(url);
    res.headers.set("Vary", "Accept");
    return res;
  }

  const res = intlMiddleware(req);

  // next-intl answers a default-locale prefix (`/ru/x` → `/x`) with a 307, and
  // 307 means "temporary": Search Console keeps the prefixed URL in its queue,
  // re-crawls it, and reports it back as a redirect page instead of dropping it
  // and consolidating its signals onto the canonical. That prefix is never
  // coming back, so the honest status is 308.
  //
  // Scoped to the DEFAULT locale on purpose. next-intl also redirects by
  // browser language (`/x` → `/en/x` for an English visitor); that one depends
  // on who is asking and must stay temporary, or the first English visitor
  // would teach every cache that the Russian page moved.
  if (res.status === 307 && res.headers.has("location") && DEFAULT_PREFIX.test(pathname)) {
    // Rebuilt rather than mutated — a NextResponse's status is read-only — and
    // the headers are carried over wholesale so Location and any cookie
    // next-intl set survive.
    return new NextResponse(null, { status: 308, headers: res.headers });
  }

  // Only negotiable URLs vary by Accept — advertise it so a CDN never serves a
  // cached HTML page to a Markdown request (or vice versa), without fragmenting
  // the cache of every other route.
  if (negotiable) res.headers.set("Vary", "Accept");

  // A flight payload is not the document and must never be stored by a shared
  // cache. Production served one AS the document for every visitor of /store:
  // the edge had been told to ignore the query string — so that ad clicks
  // carrying `?utm_source=…&fbclid=…` collapse into a single entry — and it
  // duly filed the `?_rsc=` response under the key for the plain page. The
  // whole storefront then answered with raw `text/x-component`.
  //
  // The edge rule is fixed too, but this is the half that does not depend on
  // one dashboard setting staying right. `private` is the load-bearing word:
  // browsers may still keep it, only shared caches must not. `no-store` costs
  // little on top — Next's prefetch speed comes from its in-memory Router
  // Cache, not from the HTTP cache.
  if (isFlightRequest(req)) {
    res.headers.set("Cache-Control", "private, no-store");
  }

  return res;
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|md|.*\\..*).*)"],
};
