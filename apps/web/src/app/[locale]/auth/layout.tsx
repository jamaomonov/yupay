import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/** Email-link landings (verify / reset) and the forgot-password form.
 *
 * These carry single-use tokens in the query string, so on top of this
 * `noindex` they are the one area robots.txt disallows outright: the goal there
 * is that a crawler never *fetches* the URL, since a bot that renders JS would
 * spend the token. See `robots.txt/route.ts`. */
export const metadata: Metadata = { robots: NOINDEX };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return children;
}
