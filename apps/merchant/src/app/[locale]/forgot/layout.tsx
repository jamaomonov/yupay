import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/** See `login/layout.tsx` for why this exists: `page.tsx` is a Client
 *  Component and cannot export metadata itself. */
export const metadata: Metadata = { robots: NOINDEX };

export default function ForgotLayout({ children }: { children: React.ReactNode }) {
  return children;
}
