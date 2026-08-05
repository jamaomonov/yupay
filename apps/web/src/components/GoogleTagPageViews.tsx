"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { scrubSearchParams, scrubUrl } from "@/lib/scrubUrl";

/**
 * Sends a GA4 `page_view` on client-side (SPA) navigations. The inline gtag
 * `config` in the SSR HTML reports the first pageview; this covers every route
 * change after it (gtag does not track those unless GA enhanced measurement is
 * on — sending it explicitly is reliable regardless). Skips the initial render
 * to avoid double-counting the first view. Suspense-wrapped at the call site
 * because `useSearchParams` would otherwise opt the tree out of static
 * rendering.
 */
const GA_ID = "G-0Z061SVQ11";

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

export function GoogleTagPageViews() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isFirst = useRef(true);

  useEffect(() => {
    if (isFirst.current) {
      isFirst.current = false;
      return;
    }
    // Never report the magic-link access token / email to GA (see H1).
    const qs = scrubSearchParams(searchParams.toString());
    const path = `${pathname}${qs ? `?${qs}` : ""}`;
    window.gtag?.("event", "page_view", {
      page_path: path,
      page_location: scrubUrl(window.location.href),
      page_title: document.title,
      send_to: GA_ID,
    });
  }, [pathname, searchParams]);

  return null;
}
