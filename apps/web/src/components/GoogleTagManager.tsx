import { scrubScript } from "@/lib/scrubUrl";

/** The container id. One per storefront; the mini app does not load it. */
export const GTM_ID = "GTM-5B7J6XCB";

const SCRUB_CALLS = scrubScript("_gtU");

// Google's stock snippet, with one addition in front of it: the first
// dataLayer entry is a `page_location` with the sensitive query params
// removed (the same list Metrika scrubs), so a GA4 tag inside the container
// can read {{page_location}} from the data layer instead of location.href —
// a guest's `?email=` order link must never reach Google as a page URL.
// The container is configured on Google's side; this is the only thing the
// page itself can do about it.
const GTM_SNIPPET = `window.dataLayer = window.dataLayer || [];
try { var _gtU = new URL(location.href); ${SCRUB_CALLS} window.dataLayer.push({page_location: _gtU.toString()}); } catch (e) {}
(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer',${JSON.stringify(GTM_ID)});`;

/**
 * Google Tag Manager container, production only, the same shape as
 * `YandexMetrika`: an inline loader in the SSR HTML and the `<noscript>`
 * iframe Google asks for right after `<body>`.
 *
 * Which tags fire is decided in the container, not here. Two things the
 * container must do itself: fire its GA4 / Ads tags on **History Change** as
 * well as page load (the storefront is an SPA after the first navigation),
 * and read the page URL from the `page_location` data-layer variable this
 * snippet pushes, for the reason in the comment above.
 */
export function GoogleTagManager() {
  if (process.env.NODE_ENV !== "production") {
    return null;
  }
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: GTM_SNIPPET }} />
      <noscript>
        <iframe
          src={`https://www.googletagmanager.com/ns.html?id=${GTM_ID}`}
          height="0"
          width="0"
          style={{ display: "none", visibility: "hidden" }}
          title="Google Tag Manager"
        />
      </noscript>
    </>
  );
}
