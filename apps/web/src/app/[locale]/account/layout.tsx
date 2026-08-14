import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/** The signed-in area. Exists only to override the locale layout's blanket
 *  `index: true` — see `NOINDEX`. */
export const metadata: Metadata = { robots: NOINDEX };

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return children;
}
