"use client";

import { usePathname, useSearchParams } from "next/navigation";
import Script from "next/script";
import { Suspense, useEffect, useRef } from "react";

/**
 * Yandex.Metrika counter for the public storefront. The `init` call already
 * reports the first pageview; because this is a Next.js App Router SPA, we also
 * send a `hit` on every client-side route change so navigations after the
 * initial load are counted (Metrika does not track those automatically).
 *
 * Rendered only in production so local dev / preview traffic never reaches the
 * live counter. The `<noscript>` pixel keeps no-JS visitors counted.
 */
const YM_ID = 111054393;

declare global {
  interface Window {
    ym?: (id: number, action: string, ...args: unknown[]) => void;
  }
}

/** Sends a Metrika `hit` on SPA navigations (skips the initial render, which
 *  the counter's own `init` already reports — avoids double-counting). Split
 *  out and Suspense-wrapped because `useSearchParams` otherwise opts the whole
 *  tree out of static rendering. */
function MetrikaRouteHits() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isFirst = useRef(true);

  useEffect(() => {
    if (isFirst.current) {
      isFirst.current = false;
      return;
    }
    const qs = searchParams.toString();
    const url = `${window.location.origin}${pathname}${qs ? `?${qs}` : ""}`;
    window.ym?.(YM_ID, "hit", url);
  }, [pathname, searchParams]);

  return null;
}

export function YandexMetrika() {
  if (process.env.NODE_ENV !== "production") {
    return null;
  }
  return (
    <>
      <Script id="yandex-metrika" strategy="afterInteractive">
        {`(function(m,e,t,r,i,k,a){
    m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
    m[i].l=1*new Date();
    for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
    k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
})(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=111054393', 'ym');
ym(111054393, 'init', {ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true});`}
      </Script>
      <Suspense fallback={null}>
        <MetrikaRouteHits />
      </Suspense>
      <noscript>
        <div>
          {/* eslint-disable-next-line @next/next/no-img-element -- noscript fallback pixel; next/image cannot render inside <noscript> */}
          <img
            src="https://mc.yandex.ru/watch/111054393"
            style={{ position: "absolute", left: "-9999px" }}
            alt=""
          />
        </div>
      </noscript>
    </>
  );
}
