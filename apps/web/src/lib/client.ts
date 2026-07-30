"use client";

/**
 * Browser-side API client for authenticated calls. Mirrors apps/miniapp:
 * the short-lived access token lives in localStorage; the 30-day refresh token
 * rides an HttpOnly cookie the browser sends automatically (never JS-readable),
 * with a single auto-refresh on 401. Server Components use `lib/api.ts` instead.
 */

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const ACCESS_KEY = "yupay.web.access_token";
// Legacy key: the refresh token used to be stored here. Purged on clearTokens so
// a pre-cookie session can't leave a readable 30-day token behind.
const LEGACY_REFRESH_KEY = "yupay.web.refresh_token";

export interface Tokens {
  access_token: string;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string): void {
  try {
    window.localStorage.setItem(ACCESS_KEY, access);
  } catch {
    /* storage blocked — ignore */
  }
}

export function clearTokens(): void {
  try {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(LEGACY_REFRESH_KEY);
  } catch {
    /* ignore */
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
  ) {
    super(`API ${String(status)} on ${path}`);
    this.name = "ApiError";
  }
}

async function refreshAccess(): Promise<string | null> {
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

interface ReqOpts {
  method?: string;
  body?: unknown;
  anonymous?: boolean;
  headers?: Record<string, string>;
  retry?: boolean;
}

export async function apiFetch<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const headers = new Headers(opts.headers);
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
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "type" in body && typeof body.type === "string") {
        type = body.type;
      }
    } catch {
      /* non-JSON or empty error body — leave `type` undefined */
    }
    throw new ApiError(res.status, path, type);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
