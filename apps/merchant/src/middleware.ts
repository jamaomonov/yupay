import { NextResponse, type NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

/**
 * The half of `localePrefix: "as-needed"` that lives outside the router.
 *
 * Every page in this app sits under `app/[locale]/`, so without this the
 * unprefixed URLs simply do not exist: `reseller.yupay.uz/` answered 404 in
 * production while `/ru` answered 200 — the exact inverse of what "as-needed"
 * promises, and the cabinet's own front door. next-intl's middleware is what
 * maps `/` onto the default locale and strips `/ru` back off again; the
 * routing config alone does nothing at request time.
 */
const intlMiddleware = createMiddleware(routing);

/** `/ru`, `/ru/anything` — the prefix next-intl strips for the default locale. */
const DEFAULT_PREFIX = new RegExp(`^/${routing.defaultLocale}(?=/|$)`);

/**
 * Is this a React Server Component payload rather than a document?
 *
 * Next marks client-side navigation and prefetch with an `RSC` header and a
 * `_rsc` cache-buster in the query. Either is enough on its own; both are
 * checked because a header can be stripped by an intermediary and the query
 * param survives a redirect.
 */
function isFlightRequest(req: NextRequest): boolean {
  return req.headers.has("rsc") || req.nextUrl.searchParams.has("_rsc");
}

export default function middleware(req: NextRequest): NextResponse {
  const res = intlMiddleware(req);

  // next-intl answers a default-locale prefix (`/ru/x` → `/x`) with a 307, and
  // 307 means "temporary". That prefix is never coming back, so 308 is the
  // honest status — and it is the one a browser and a CDN may actually keep.
  //
  // Scoped to the DEFAULT locale deliberately: any redirect that depends on
  // who is asking must stay temporary. `localeDetection` is off here, so there
  // are none today, but the scope is the reason the storefront's copy of this
  // is safe and this one should not drift from it.
  if (
    res.status === 307 &&
    res.headers.has("location") &&
    DEFAULT_PREFIX.test(req.nextUrl.pathname)
  ) {
    // Rebuilt rather than mutated — a NextResponse's status is read-only — and
    // the headers are carried over wholesale so Location survives.
    return new NextResponse(null, { status: 308, headers: res.headers });
  }

  // A flight payload is not the document and must never be stored by a shared
  // cache. The storefront served one AS the document for every visitor of
  // /store once, because the edge was told to ignore the query string and
  // filed the `?_rsc=` response under the plain page's key. This origin is
  // behind the same Cloudflare, so it carries the same guard — the one that
  // does not depend on a dashboard setting staying right.
  if (isFlightRequest(req)) {
    res.headers.set("Cache-Control", "private, no-store");
  }

  return res;
}

/**
 * Everything but Next's own internals and anything with a file extension.
 *
 * Note what is **not** excluded: `api`. The sibling apps exclude it because
 * they serve Route Handlers from `app/api/*`; this app serves none — `/api`
 * here is a marketing page under `app/[locale]/api`. With `api` in the
 * lookahead the unprefixed `/api` never reached next-intl, so the RU
 * canonical 404'd while `/uz/api` and `/en/api` answered 200: the same
 * failure the site root had before this file existed.
 *
 * If a Route Handler is ever added to this app, put its own prefix back in
 * the lookahead — not the word `api`, which is now a page.
 */
export const config = {
  matcher: ["/((?!_next|_vercel|.*\\..*).*)"],
};
