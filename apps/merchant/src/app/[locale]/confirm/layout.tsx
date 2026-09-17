import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/**
 * See `login/layout.tsx` for why this exists: `page.tsx` is a Client
 * Component and cannot export metadata itself. `/confirm` also carries a
 * single-use email-confirmation token in the query string — `robots.txt`
 * disallows it outright for the same reason the storefront disallows
 * `/auth/`: a bot that renders JS would spend the token before the real
 * recipient could.
 */
export const metadata: Metadata = { robots: NOINDEX };

export default function ConfirmLayout({ children }: { children: React.ReactNode }) {
  return children;
}
