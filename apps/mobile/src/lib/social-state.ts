/**
 * The round trip through the storefront's `/app-auth` page (ADR-0101): the state the app
 * sends, and reading what comes back. Plain TS, unit-tested.
 */

export type Provider = "google" | "telegram";

function toBase64Url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** `{to, n, l}`: where the page returns, a nonce to check on the way back, the language. */
export function encodeState(to: string, nonce: string, locale: string): string {
  return toBase64Url(JSON.stringify({ to, n: nonce, l: locale }));
}

/** Base64 (standard or url-safe) of UTF-8 text — a Telegram name can be Cyrillic. */
export function decodeBase64Utf8(value: string): string {
  const normal = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normal + "=".repeat((4 - (normal.length % 4)) % 4);
  const binary = atob(padded);
  let escaped = "";
  for (let i = 0; i < binary.length; i += 1) {
    escaped += `%${binary.charCodeAt(i).toString(16).padStart(2, "0")}`;
  }
  return decodeURIComponent(escaped);
}

export type SocialResult =
  | { provider: "google"; accessToken: string }
  | { provider: "telegram"; payload: Record<string, unknown> }
  | { error: true };

/**
 * What the page handed back, or an error. A `state` that is not the one sent means the
 * answer was not for this attempt and is dropped.
 */
export function readResult(params: Record<string, string | undefined>, sent: string): SocialResult {
  if (params.state !== sent || params.error !== undefined) return { error: true };
  if (params.provider === "google" && params.access_token) {
    return { provider: "google", accessToken: params.access_token };
  }
  if (params.provider === "telegram" && params.tg) {
    try {
      const payload: unknown = JSON.parse(decodeBase64Utf8(params.tg));
      if (typeof payload === "object" && payload !== null && "hash" in payload) {
        return { provider: "telegram", payload: payload as Record<string, unknown> };
      }
    } catch {
      // A declined Telegram prompt answers `tgAuthResult=false`, or junk: an error either way.
    }
  }
  return { error: true };
}
