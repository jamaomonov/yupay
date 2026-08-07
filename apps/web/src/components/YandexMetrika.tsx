import { Suspense } from "react";

import { YandexMetrikaHits } from "./YandexMetrikaHits";

/**
 * Yandex.Metrika counter for the public storefront (id 111054393).
 *
 * The counter is rendered as a raw inline <script> in the SERVER HTML — not via
 * next/script — on purpose: the `init` config uses `ssr:true`, and Metrika's own
 * verification (`?_ym_status-check`, `?_ym_debug`) plus earliest-possible bounce
 * tracking all require the snippet to be present in the initial document, exactly
 * as Yandex's install instructions expect. An `afterInteractive` script (injected
 * only after hydration) is absent from the SSR HTML and fails that verification.
 *
 * SPA route changes are tracked by <YandexMetrikaHits> (the `init` here only
 * reports the first pageview). Rendered only in production so local dev / preview
 * traffic never reaches the live counter; the <noscript> pixel covers no-JS.
 *
 * `dataLayer` is declared here because `ecommerce:"dataLayer"` names the array
 * the counter watches. It used to be created as a side effect of the Google tag
 * snippet, which has since been removed; nothing pushes ecommerce events yet, so
 * the array stays empty, but the counter no longer depends on a deleted script.
 */
const YM_SNIPPET = `window.dataLayer = window.dataLayer || [];
(function(m,e,t,r,i,k,a){
    m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
    m[i].l=1*new Date();
    for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
    k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
})(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=111054393', 'ym');
var _ymUrl = location.href, _ymOrder = location.pathname.indexOf('/orders/') !== -1;
try { var _ymU = new URL(_ymUrl); _ymU.searchParams.delete('access'); _ymU.searchParams.delete('email'); _ymUrl = _ymU.toString(); } catch (e) {}
ym(111054393, 'init', {ssr:true, webvisor:!_ymOrder, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: _ymUrl, accurateTrackBounce:true, trackLinks:true});`;

export function YandexMetrika() {
  if (process.env.NODE_ENV !== "production") {
    return null;
  }
  return (
    <>
      {/* Trusted first-party Yandex.Metrika snippet; must be inline in the SSR
          HTML for the counter to be verifiable and to track earliest. */}
      <script dangerouslySetInnerHTML={{ __html: YM_SNIPPET }} />
      <Suspense fallback={null}>
        <YandexMetrikaHits />
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
