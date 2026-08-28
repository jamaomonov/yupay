import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

/**
 * Locale routing, and nothing else.
 *
 * The storefront's middleware also negotiates Markdown for agents and marks
 * RSC payloads as uncacheable; neither applies here. A partner site is not
 * crawled for agent consumption, and it has no CDN-cached pages — the landing
 * is prerendered and the panel is private.
 */
export default createMiddleware(routing);

export const config = {
  // Everything except Next's internals and files with an extension.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
