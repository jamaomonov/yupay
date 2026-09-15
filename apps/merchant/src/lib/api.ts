/**
 * The cabinet's HTTP client.
 *
 * Talks only to `/merchant/cabinet/*` — the BFF — and never to
 * `/merchant/v1`. That separation is the point: `/merchant/v1` is signed with
 * a merchant's HMAC secret, which belongs on their server and must never reach
 * a browser. This client carries a short-lived access token instead.
 *
 * Tokens live in `localStorage` rather than a cookie, because the cabinet is
 * a separate origin from the API and a cookie would need third-party
 * semantics that browsers are actively removing. The trade is the usual one:
 * an XSS on this origin can read them. The mitigations are the access token's
 * 15 minutes and a refresh that rotates — a stolen refresh works once, and the
 * theft surfaces as the real operator's next refresh failing.
 */

import { LOCALES } from "@yupay/i18n";

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const ACCESS_KEY = "yupay.merchant.access";
const REFRESH_KEY = "yupay.merchant.refresh";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** A problem+json body, as far as the cabinet cares about it. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly body: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    super(typeof body.detail === "string" ? body.detail : `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = typeof body.code === "string" ? body.code : null;
    this.body = body;
  }
}

function readToken(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private mode, or a browser set to block site data. The cabinet then
    // behaves as signed-out, which is honest: nothing can be kept.
    return null;
  }
}

export function storeTokens(tokens: Tokens): void {
  try {
    window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
    window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  } catch {
    /* see readToken */
  }
}

export function clearTokens(): void {
  try {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* see readToken */
  }
}

export function hasSession(): boolean {
  return readToken(ACCESS_KEY) !== null;
}

export function refreshToken(): string | null {
  return readToken(REFRESH_KEY);
}

async function parse(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return { detail: text };
  }
}

async function rotate(): Promise<boolean> {
  const token = readToken(REFRESH_KEY);
  if (!token) return false;
  const response = await fetch(`${BASE}/merchant/cabinet/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  });
  if (!response.ok) {
    clearTokens();
    return false;
  }
  storeTokens((await response.json()) as Tokens);
  return true;
}

/**
 * Send the browser back to the sign-in form, once.
 *
 * A session that cannot be rotated is gone, and every screen in the cabinet
 * renders an *empty state* when its read fails — so without this a reseller
 * whose refresh lapsed sees "no orders", "no webhook" and a dash where their
 * balance was, and reasonably concludes their account broke. The redirect is
 * what turns that into "you are signed out".
 *
 * `location.assign` rather than a router push: this runs inside the HTTP
 * client, below every component, and a full load is also the cheapest way to
 * be sure nothing stale is left in memory.
 */
/**
 * Where a signed-out reader belongs, from where they are now.
 *
 * Exported for its own test: `localePrefix: "as-needed"` means the default
 * locale has **no** segment at all, so "the first path segment" is only
 * sometimes a locale — and getting that wrong sends an English reader to a
 * Russian form, which is exactly the kind of thing nobody notices by hand.
 */
export function loginPathFor(pathname: string): string {
  const [, first = ""] = pathname.split("/");
  const prefix = LOCALES.includes(first as (typeof LOCALES)[number]) ? `/${first}` : "";
  return `${prefix}/login`;
}

function returnToLogin(): void {
  if (typeof window === "undefined") return;
  const target = loginPathFor(window.location.pathname);
  if (window.location.pathname !== target) window.location.assign(target);
}

interface Options {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /**
   * Sent as `Idempotency-Key`. Mint one per *intent* — per click, held in
   * state so a retry of the same click carries the same key — never per
   * request: a fresh key on every attempt is the same as having none.
   * The API refuses anything shorter than 16 characters, so a UUID.
   */
  idempotencyKey?: string;
  body?: unknown;
  /** Set by the retry below; callers never pass it. */
  retried?: boolean;
  /** Endpoints that are reached before there is a session. */
  anonymous?: boolean;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, retried = false, anonymous = false, idempotencyKey } = options;
  const access = anonymous ? null : readToken(ACCESS_KEY);
  const response = await fetch(`${BASE}/merchant/cabinet${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(access ? { Authorization: `Bearer ${access}` } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  if (response.status === 401 && !anonymous) {
    // Once. A second 401 after a successful rotation is not an expiry, it is
    // a revoked session, and retrying forever would hide that behind a
    // spinner.
    if (!retried && (await rotate())) return api<T>(path, { ...options, retried: true });
    clearTokens();
    returnToLogin();
  }
  if (!response.ok) throw new ApiError(response.status, await parse(response));
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/**
 * Fetch a file from the cabinet and hand it to the browser to save.
 *
 * A plain `<a href>` cannot carry the `Authorization` header, so the bytes
 * come through `fetch` and reach the disk as an object URL. The filename is
 * read off `Content-Disposition` — the API names the statement after the date
 * range it actually covers — which is why `Content-Disposition` is on the
 * CORS `expose_headers` list; without that a browser on this origin cannot
 * see the header at all.
 */
export async function downloadFile(path: string, retried = false): Promise<void> {
  const access = readToken(ACCESS_KEY);
  const response = await fetch(`${BASE}/merchant/cabinet${path}`, {
    headers: access ? { Authorization: `Bearer ${access}` } : {},
  });
  if (response.status === 401 && !retried && (await rotate())) {
    return downloadFile(path, true);
  }
  if (!response.ok) throw new ApiError(response.status, await parse(response));

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const name = match?.[1] ?? "export.csv";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function signOut(): Promise<void> {
  const token = readToken(REFRESH_KEY);
  // Clear locally first: a network failure must not leave a browser that looks
  // signed in. The server-side revoke is best effort on top of that.
  clearTokens();
  if (token) {
    try {
      await fetch(`${BASE}/merchant/cabinet/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: token }),
      });
    } catch {
      /* the session still expires on its own */
    }
  }
}
