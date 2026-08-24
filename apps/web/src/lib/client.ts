"use client";

/**
 * Browser-side API client for authenticated calls.
 *
 * The short-lived access token lives **in memory only** (a module variable), so
 * an XSS payload can't read it out of localStorage; the 30-day refresh token
 * rides an HttpOnly cookie the browser sends automatically (never JS-readable).
 * On a fresh page load the in-memory token is gone, so it is re-hydrated from
 * the refresh cookie (see `refreshAccess` + the `has_session` hint below).
 * Server Components use `lib/api.ts` instead.
 */

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

// Non-secret hint that a session *might* exist, so anonymous visitors don't fire
// a refresh on every page load. Safe to keep in localStorage — it's a boolean,
// not a credential. The actual access token never touches storage.
const SESSION_HINT_KEY = "yupay.web.has_session";
// Legacy keys from when tokens were stored in localStorage — purged on clear so a
// pre-refactor session can't leave a readable access/refresh token behind.
const LEGACY_ACCESS_KEY = "yupay.web.access_token";
const LEGACY_REFRESH_KEY = "yupay.web.refresh_token";

export interface Tokens {
  access_token: string;
}

// In-memory access token — never persisted. Lost on reload, re-hydrated via cookie.
let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setTokens(access: string): void {
  accessToken = access;
  try {
    window.localStorage.setItem(SESSION_HINT_KEY, "1");
    window.localStorage.removeItem(LEGACY_ACCESS_KEY);
  } catch {
    /* storage blocked — the in-memory token still works for this tab */
  }
}

export function clearTokens(): void {
  accessToken = null;
  try {
    window.localStorage.removeItem(SESSION_HINT_KEY);
    window.localStorage.removeItem(LEGACY_ACCESS_KEY);
    window.localStorage.removeItem(LEGACY_REFRESH_KEY);
  } catch {
    /* ignore */
  }
}

/** Whether a prior session hint exists — gate for attempting a silent refresh. */
export function hasSessionHint(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(SESSION_HINT_KEY) === "1";
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
    /**
     * RFC 7807 `type` URI from the problem+json error body (e.g.
     * `https://app.yupay.uz/errors/email-unverified`), when the response body
     * was parseable JSON with a `type` string. `undefined` for non-JSON
     * bodies or bodies without a `type` field — callers that need to
     * distinguish error kinds should check this rather than status alone.
     */
    public type?: string,
    /**
     * The problem+json `detail` — the API writes these for the customer
     * ("amount is below the minimum", "payment provider is not accepting new
     * payments"), so a caller that shows one tells them something they can act
     * on instead of a single house error string.
     */
    public detail?: string,
  ) {
    super(`API ${String(status)} on ${path}`);
    this.name = "ApiError";
  }
}

// Dedup concurrent refreshes *within* a tab so N parallel 401s share one call.
let inFlightRefresh: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  // The refresh token rides an HttpOnly cookie — `credentials: "include"` makes the
  // browser send it (and store the rotated one). No token in the request body.
  const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    clearTokens();
    return null;
  }
  const tokens = (await res.json()) as Tokens;
  setTokens(tokens.access_token);
  return tokens.access_token;
}

/**
 * Re-mint the access token from the HttpOnly refresh cookie.
 *
 * Serialised two ways so our **rotating** refresh token is never presented twice
 * concurrently — the server's reuse-detection would treat that as theft and
 * revoke every session. In-tab: a shared `inFlightRefresh` promise. Cross-tab:
 * the Web Locks API, so a second tab waits and then refreshes against the
 * already-rotated cookie instead of racing the same one.
 */
export async function refreshAccess(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;
  const run =
    typeof navigator !== "undefined" && navigator.locks
      ? () => navigator.locks.request("yupay-token-refresh", doRefresh)
      : doRefresh;
  inFlightRefresh = Promise.resolve(run()).finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

interface ReqOpts {
  method?: string;
  body?: unknown;
  anonymous?: boolean;
  headers?: Record<string, string>;
  retry?: boolean;
}

/** Which of our surfaces this bundle is. Sent on every call so an order can
 *  record where it came from — nothing stored it before, and the only hint was
 *  Click's per-surface merchant service, which covered a tenth of orders and
 *  said nothing about the ones never paid. Advisory: the server gates nothing
 *  on it.
 *
 *  Exported because `apiFetch` is not the only way this app reaches the API:
 *  checkout and the guest helpers call `fetch` directly, and every one of them
 *  was omitting the header — which is why every web order landed as `unknown`
 *  while the mini app's landed as `miniapp`. Import this rather than repeating
 *  the literal, so the next raw call site has one obvious thing to reach for. */
export const SURFACE = "web";

export async function apiFetch<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  headers.set("X-Yupay-Surface", SURFACE);
  if (opts.body !== undefined) headers.set("Content-Type", "application/json");
  const token = getAccessToken();
  if (!opts.anonymous && token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${BASE}/api/v1${path}`, {
    method: opts.method ?? "GET",
    headers,
    // Send the auth cookie so login/refresh can set/rotate the HttpOnly refresh
    // token and logout can clear it. Harmless on other calls (server ignores it).
    credentials: "include",
    // exactOptionalPropertyTypes: `body` must be BodyInit | null, not undefined
    ...(opts.body !== undefined && { body: JSON.stringify(opts.body) }),
  });

  if (res.status === 401 && !opts.anonymous && !opts.retry) {
    const fresh = await refreshAccess();
    if (fresh) return apiFetch<T>(path, { ...opts, retry: true });
  }
  if (!res.ok) {
    let type: string | undefined;
    let detail: string | undefined;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object") {
        if ("type" in body && typeof body.type === "string") type = body.type;
        if ("detail" in body && typeof body.detail === "string") detail = body.detail;
      }
    } catch {
      /* non-JSON or empty error body — leave both undefined */
    }
    throw new ApiError(res.status, path, type, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
