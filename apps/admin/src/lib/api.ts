/**
 * HTTP client for the admin SPA.
 *
 * Reads/writes the access JWT from/to localStorage, attaches it as a Bearer header,
 * and surfaces 401/403/non-2xx as typed exceptions so the UI can react explicitly.
 *
 * When a request comes back ``401`` AND a refresh token is in storage, the
 * client transparently calls ``POST /api/v1/auth/refresh`` once, swaps both
 * tokens in localStorage, and replays the original request. The refresh
 * itself is single-flight: parallel 401s from React Query / WebSocket /
 * tab-focus revalidations share one in-flight refresh promise, so we
 * never invalidate a fresh rotating-refresh-token by issuing N concurrent
 * rotates.
 */

const TOKEN_KEY = "yupay.admin.access_token";
const REFRESH_KEY = "yupay.admin.refresh_token";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: unknown,
  ) {
    super(`${status.toString()} ${statusText}`);
    this.name = "ApiError";
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(access: string, refresh: string | null): void {
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export interface RequestOptions extends RequestInit {
  /** When true, omit the Authorization header even if a token is stored. */
  anonymous?: boolean;
}

/** Callbacks the auth store registers so the API layer can wake the
 *  Zustand state up when it rotates a token (or wipes them on a hard
 *  failure). We do this through a registration hook rather than a
 *  direct import to avoid the cycle ``api → authStore → api``. */
interface AuthBridge {
  onTokensRotated: (access: string, refresh: string | null) => void;
  onAuthLost: () => void;
}

let bridge: AuthBridge | null = null;

export function registerAuthBridge(b: AuthBridge): void {
  bridge = b;
}

/** Single-flight refresh promise. ``null`` whenever no refresh is in flight. */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  // De-dupe concurrent callers — they all await the same promise.
  if (refreshInFlight !== null) return refreshInFlight;
  const refresh = getRefreshToken();
  if (!refresh) return false;

  refreshInFlight = (async (): Promise<boolean> => {
    try {
      const resp = await fetch(`${apiBase}/api/v1/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!resp.ok) {
        // 401 / 422 / 5xx on refresh all mean "session is dead". Wipe
        // tokens so the rest of the app falls back to the login page
        // instead of looping.
        clearTokens();
        bridge?.onAuthLost();
        return false;
      }
      const body = (await resp.json()) as {
        access_token?: string;
        refresh_token?: string | null;
      };
      if (!body.access_token) {
        clearTokens();
        bridge?.onAuthLost();
        return false;
      }
      // Rotating-refresh: the backend mints a brand-new refresh too.
      // Preserve the old one only if the response somehow lacks the field.
      const nextRefresh = body.refresh_token ?? refresh;
      setTokens(body.access_token, nextRefresh);
      bridge?.onTokensRotated(body.access_token, nextRefresh);
      return true;
    } catch {
      // Network error: don't wipe — the user might just be offline. The
      // outer caller will surface the original 401 to the UI.
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  return apiRaw<T>(path, options, /* allowRefresh */ true);
}

async function apiRaw<T>(path: string, options: RequestOptions, allowRefresh: boolean): Promise<T> {
  const { anonymous, headers, ...init } = options;
  const url = path.startsWith("http") ? path : `${apiBase}${path}`;
  const h = new Headers(headers);
  h.set("Accept", "application/json");
  if (init.body && !h.has("Content-Type")) h.set("Content-Type", "application/json");
  if (!anonymous) {
    const token = getAccessToken();
    if (token) h.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...init, headers: h });

  // Auto-refresh on a single 401, but only for authenticated calls and
  // only once per call (``allowRefresh`` guards the recursion).
  if (
    response.status === 401 &&
    allowRefresh &&
    !anonymous &&
    !path.includes("/auth/refresh") &&
    getRefreshToken()
  ) {
    const ok = await refreshAccessToken();
    if (ok) {
      // Replay the exact same request with the new access token.
      return apiRaw<T>(path, options, /* allowRefresh */ false);
    }
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, response.statusText, body);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const apiGet = <T>(path: string) => api<T>(path);
export const apiPost = <T>(path: string, body: unknown, headers?: HeadersInit) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    ...(headers ? { headers } : {}),
  });
export const apiPatch = <T>(path: string, body: unknown, headers?: HeadersInit) =>
  api<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
    ...(headers ? { headers } : {}),
  });
export const apiDelete = (path: string) => api<void>(path, { method: "DELETE" });
