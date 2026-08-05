"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { scrubSearchParams } from "@/lib/scrubUrl";

/**
 * Sends a Yandex.Metrika `hit` on client-side (SPA) navigations. The inline
 * counter snippet in the SSR HTML reports the first pageview via `init`; this
 * covers every route change after it (Metrika does not track those on its own).
 * Skips the initial render to avoid double-counting the first view. Kept a
 * separate client unit so the server-rendered counter script stays in the
 * initial HTML; Suspense-wrapped at the call site because `useSearchParams`
 * would otherwise opt the tree out of static rendering.
 */
const YM_ID = 111054393;

declare global {
  interface Window {
    ym?: (id: number, action: string, ...args: unknown[]) => void;
  }
}

export function YandexMetrikaHits() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isFirst = useRef(true);

  useEffect(() => {
    if (isFirst.current) {
      isFirst.current = false;
      return;
    }
    // Never report the magic-link access token / email to Metrika (see H1).
    const qs = scrubSearchParams(searchParams.toString());
    const url = `${window.location.origin}${pathname}${qs ? `?${qs}` : ""}`;
    window.ym?.(YM_ID, "hit", url);
  }, [pathname, searchParams]);

  return null;
}
