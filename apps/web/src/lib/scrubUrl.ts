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
 * This list is the single source of truth: the Metrika counter's inline snippet
 * generates its own `delete` calls from it (see `YandexMetrika.tsx`) rather than
 * repeating the names, because the drift between two hand-kept copies is exactly
 * how `token` came to be scrubbed on SPA navigations but not on first load. */
export const SENSITIVE_PARAMS = ["access", "email", "token"] as const;

/** Return `href` with every {@link SENSITIVE_PARAMS} query param removed. */
export function scrubUrl(href: string): string {
  try {
    const u = new URL(href);
    for (const p of SENSITIVE_PARAMS) u.searchParams.delete(p);
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
  for (const p of SENSITIVE_PARAMS) params.delete(p);
  return params.toString();
}
