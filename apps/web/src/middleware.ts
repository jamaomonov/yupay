import { NextResponse, type NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

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
  // Only negotiable URLs vary by Accept — advertise it so a CDN never serves a
  // cached HTML page to a Markdown request (or vice versa), without fragmenting
  // the cache of every other route.
  if (negotiable) res.headers.set("Vary", "Accept");
  return res;
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|md|.*\\..*).*)"],
};
