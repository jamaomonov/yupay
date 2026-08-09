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
  return res;
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|md|.*\\..*).*)"],
};
