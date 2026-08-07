/**
 * The origin the browser opens a connection to before it can fetch anything
 * from the API, or `null` when the API is same-origin (nothing to preconnect).
 *
 * Measured against production on /store/steam: DNS + TCP + TLS to api.yupay.uz
 * costs 190–435 ms, paid at first use rather than in parallel with the document.
 * A `preconnect` hint moves that handshake to the start of the load.
 *
 * Derived from the same env var the browser-side calls use, so the hint can't
 * drift from the origin actually contacted — a preconnect to an origin nobody
 * requests is a wasted connection, not a free one.
 */
export function apiPreconnectOrigin(siteOrigin: string): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) return null;
  try {
    const origin = new URL(base).origin;
    return origin === siteOrigin ? null : origin;
  } catch {
    return null;
  }
}
