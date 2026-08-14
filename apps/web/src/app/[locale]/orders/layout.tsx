import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/** Per-order tracking pages — one URL per buyer, no search value. Overrides the
 *  locale layout's blanket `index: true`; see `NOINDEX`. */
export const metadata: Metadata = { robots: NOINDEX };

export default function OrdersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
