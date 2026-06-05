"use client";

/**
 * Browser-side API client for authenticated calls. Mirrors apps/miniapp:
 * access + refresh tokens in localStorage with a single auto-refresh on 401.
 * Server Components must keep using `lib/api.ts` instead.
 */

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const ACCESS_KEY = "yupay.web.access_token";
const REFRESH_KEY = "yupay.web.refresh_token";

export interface Tokens {
  access_token: string;
  refresh_token?: string | null;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string, refresh?: string | null): void {
  try {
    window.localStorage.setItem(ACCESS_KEY, access);
    if (refresh) window.localStorage.setItem(REFRESH_KEY, refresh);
  } catch {
    /* storage blocked — ignore */
  }
}

export function clearTokens(): void {
  try {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
  ) {
    super(`API ${String(status)} on ${path}`);
    this.name = "ApiError";
  }
}

async function refreshAccess(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) {
    clearTokens();
    return null;
  }
  const tokens = (await res.json()) as Tokens;
  setTokens(tokens.access_token, tokens.refresh_token ?? null);
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
    // exactOptionalPropertyTypes: `body` must be BodyInit | null, not undefined
    ...(opts.body !== undefined && { body: JSON.stringify(opts.body) }),
  });

  if (res.status === 401 && !opts.anonymous && !opts.retry) {
    const fresh = await refreshAccess();
    if (fresh) return apiFetch<T>(path, { ...opts, retry: true });
  }
  if (!res.ok) throw new ApiError(res.status, path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
