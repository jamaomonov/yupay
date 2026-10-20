/**
 * Strip secrets from a URL before it is reported to analytics / third parties.
 *
 * The guest order magic-link carries an order-scoped access JWT and the buyer's
 * email in the query string (`/orders/{id}?access=<jwt>&email=<email>`). Those
 * must never reach Yandex Metrika / Google Analytics — a recorded URL would let
 * anyone with analytics access replay the token for the buyer's codes, and the
 * email is PII (AGENTS.md §9). See the H1 finding / ADR-0042.
 *
 * `token` was missing from this list until Yandex's crawl log surfaced
 * `/en/auth/verify?token=eyJhbGciOi…` — Metrika had reported the first pageview
 * of an email link verbatim, so Yandex learned the URL and went to fetch it.
 * The same query param carries the password-reset token
 * (`auth/service.py` builds `/auth/verify?token=` and `/auth/reset?token=`),
 * which makes it the most sensitive of the three.
 */

/** Query params that must be removed before a URL leaves the browser to analytics.
 *
 * This list is the single source of truth: the Metrika and GTM inline snippets
 * build their scrubbing from it (see {@link scrubScript}) rather than repeating
 * the names, because the drift between two hand-kept copies is exactly how
 * `token` came to be scrubbed on SPA navigations but not on first load.
 *
 * `steam_login` / `username` are the recipient a link hands to a product page
 * (the home page's quick form used to). Who a gift is for is nobody's
 * analytics. */
export const SENSITIVE_PARAMS = ["access", "email", "token", "steam_login", "username"] as const;

/** Whole families of params. `openid.*` is Steam's sign-in assertion on
 * `/auth/steam/callback` — a one-time login credential with the SteamID64 in
 * it, which Metrika and GTM used to receive as the page URL. */
export const SENSITIVE_PREFIXES = ["openid."] as const;

/** Whether a query param name must never reach analytics. */
export function isSensitiveParam(name: string): boolean {
  return (
    (SENSITIVE_PARAMS as readonly string[]).includes(name) ||
    SENSITIVE_PREFIXES.some((prefix) => name.startsWith(prefix))
  );
}

function scrubParams(params: URLSearchParams): void {
  // Collected first: deleting while iterating a URLSearchParams skips entries.
  const drop = [...params.keys()].filter(isSensitiveParam);
  for (const name of drop) params.delete(name);
}

/** Return `href` with every sensitive query param removed. */
export function scrubUrl(href: string): string {
  try {
    const u = new URL(href);
    scrubParams(u.searchParams);
    return u.toString();
  } catch {
    // Not an absolute URL we can parse — return unchanged rather than throw in
    // an analytics hot path; the callers only ever pass real location URLs.
    return href;
  }
}

/** Return a `URLSearchParams`-style query string with sensitive params removed. */
export function scrubSearchParams(search: string): string {
  const params = new URLSearchParams(search);
  scrubParams(params);
  return params.toString();
}

/** ES5 for an inline snippet: removes every sensitive param from the `URL`
 * object held in the global `urlVar`. Generated from the same lists as
 * {@link isSensitiveParam}, so the first page view and SPA hits agree. */
export function scrubScript(urlVar: string): string {
  const names = JSON.stringify(SENSITIVE_PARAMS);
  const prefixes = JSON.stringify(SENSITIVE_PREFIXES);
  return (
    `(function(u){var n=${names},p=${prefixes},d=[];` +
    `u.searchParams.forEach(function(v,k){if(n.indexOf(k)>=0){d.push(k);return;}` +
    `for(var i=0;i<p.length;i++){if(k.indexOf(p[i])===0){d.push(k);return;}}});` +
    `for(var j=0;j<d.length;j++){u.searchParams.delete(d[j]);}})(${urlVar});`
  );
}
