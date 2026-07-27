import { Suspense } from "react";

import { GoogleTagPageViews } from "./GoogleTagPageViews";

/**
 * Google tag (gtag.js / GA4, id G-0Z061SVQ11) for the public storefront.
 *
 * Rendered from the SERVER layout so the tag sits in the initial HTML head, as
 * Google's install expects. The async gtag.js loader + the inline `config`
 * (which fires the first pageview) mirror Google's snippet verbatim; SPA route
 * changes are tracked by <GoogleTagPageViews> (the `config` only reports the
 * first view). Rendered only in production so dev / preview traffic never
 * reaches the live property.
 *
 * NOTE: the storefront CSP (infra/caddy/Caddyfile.prod) must allow
 * www.googletagmanager.com in script-src and *.google-analytics.com /
 * googletagmanager.com in connect-src, or the browser blocks the tag — same
 * class of block we hit with Yandex.Metrika.
 */
const GA_ID = "G-0Z061SVQ11";

export function GoogleTag() {
  if (process.env.NODE_ENV !== "production") {
    return null;
  }
  return (
    <>
      <script async src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`} />
      {/* Trusted first-party Google tag config; inline in the SSR HTML per
          Google's install snippet. */}
      <script
        dangerouslySetInnerHTML={{
          __html: `window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', '${GA_ID}');`,
        }}
      />
      <Suspense fallback={null}>
        <GoogleTagPageViews />
      </Suspense>
    </>
  );
}
