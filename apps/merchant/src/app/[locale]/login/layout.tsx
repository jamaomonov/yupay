import type { Metadata } from "next";

import { NOINDEX } from "@/lib/seo";

/**
 * `page.tsx` here is `"use client"` (a form with local state), and a Client
 * Component cannot export `metadata`/`generateMetadata` — Next requires that
 * boundary to be a Server Component. Same shape the storefront uses for its
 * own auth screens (`apps/web/src/app/[locale]/auth/layout.tsx`): a layout
 * that exists only to carry `robots: NOINDEX` for the page beneath it.
 */
export const metadata: Metadata = { robots: NOINDEX };

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
