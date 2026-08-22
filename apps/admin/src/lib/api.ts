/**
 * HTTP client for the admin SPA.
 *
 * Keeps the access JWT in memory (never localStorage, so an XSS payload can't
 * read it), attaches it as a Bearer header, and surfaces 401/403/non-2xx as
 * typed exceptions so the UI can react explicitly. The in-memory token is
 * re-hydrated from the HttpOnly refresh cookie on boot (see the auth store).
 *
 * When a request comes back ``401`` the client transparently calls
 * ``POST /api/v1/auth/refresh`` once (the 30-day refresh token rides an HttpOnly
 * cookie the browser sends automatically — never JS-readable), swaps the access
 * token in localStorage, and replays the original request. The refresh itself is
 * single-flight: parallel 401s from React Query / WebSocket / tab-focus
 * revalidations share one in-flight refresh promise, so we never invalidate a
 * fresh rotating-refresh-token by issuing N concurrent rotates.
 */

// Non-secret hint that a session might exist, so a fresh load can decide whether
// to attempt a silent refresh. Safe in localStorage — it's a boolean, not a token.
const SESSION_HINT_KEY = "yupay.admin.has_session";
// Legacy keys from when tokens were stored in localStorage — purged on clear so a
// pre-refactor session can't leave a JS-readable access/refresh token behind.
const LEGACY_ACCESS_KEY = "yupay.admin.access_token";
const LEGACY_REFRESH_KEY = "yupay.admin.refresh_token";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

// In-memory access token — never persisted, so an XSS payload can't read it out
// of localStorage. Lost on reload; re-hydrated from the refresh cookie on boot.
let accessToken: string | null = null;

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
  return accessToken;
}

/** Whether a prior session hint exists — gate for attempting a silent refresh. */
export function hasSessionHint(): boolean {
  try {
    return localStorage.getItem(SESSION_HINT_KEY) === "1";
  } catch {
    return false;
  }
}

/** Keep the access token in memory. The second arg is accepted for call-site
 *  compatibility (the refresh token lives in an HttpOnly cookie) and is ignored. */
export function setTokens(access: string, _refresh?: string | null): void {
  accessToken = access;
  try {
    localStorage.setItem(SESSION_HINT_KEY, "1");
    localStorage.removeItem(LEGACY_ACCESS_KEY);
  } catch {
    /* storage blocked — the in-memory token still works for this tab */
  }
}

export function clearTokens(): void {
  accessToken = null;
  localStorage.removeItem(SESSION_HINT_KEY);
  localStorage.removeItem(LEGACY_ACCESS_KEY);
  localStorage.removeItem(LEGACY_REFRESH_KEY);
  // Ask the server to revoke the session and expire the HttpOnly refresh cookie —
  // JS can't delete it. Fire-and-forget: logout must never block or throw.
  void fetch(`${apiBase}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {
    /* fire-and-forget logout — ignore network/revocation errors */
  });
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
  onTokensRotated: (access: string) => void;
  onAuthLost: () => void;
}

let bridge: AuthBridge | null = null;

export function registerAuthBridge(b: AuthBridge): void {
  bridge = b;
}

/** Single-flight refresh promise. ``null`` whenever no refresh is in flight. */
let refreshInFlight: Promise<boolean> | null = null;

async function _doRefresh(): Promise<boolean> {
  try {
    // The refresh token rides an HttpOnly cookie; `credentials: "include"` sends
    // it and stores the rotated one. No token in the request body.
    const resp = await fetch(`${apiBase}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) {
      // 401 / 422 / 5xx on refresh all mean "session is dead" (or no cookie).
      // Wipe tokens so the rest of the app falls back to the login page
      // instead of looping.
      clearTokens();
      bridge?.onAuthLost();
      return false;
    }
    const body = (await resp.json()) as { access_token?: string };
    if (!body.access_token) {
      clearTokens();
      bridge?.onAuthLost();
      return false;
    }
    setTokens(body.access_token);
    bridge?.onTokensRotated(body.access_token);
    return true;
  } catch {
    // Network error: don't wipe — the user might just be offline. The
    // outer caller will surface the original 401 to the UI.
    return false;
  }
}

/**
 * Re-mint the access token from the HttpOnly refresh cookie. Serialised so our
 * rotating refresh token is never presented twice concurrently (the server's
 * reuse-detection would treat that as theft). In-tab: the shared
 * `refreshInFlight` promise. Cross-tab: the Web Locks API, so a second tab waits
 * and refreshes against the already-rotated cookie instead of racing the same one.
 * Exported so the auth store can re-hydrate the in-memory token on app boot.
 */
export async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight !== null) return refreshInFlight;
  const run =
    typeof navigator !== "undefined" && navigator.locks
      ? () => navigator.locks.request("yupay-admin-token-refresh", _doRefresh)
      : _doRefresh;
  refreshInFlight = Promise.resolve(run()).finally(() => {
    refreshInFlight = null;
  });
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

  // Send the auth cookie so login/refresh can set/rotate the HttpOnly refresh
  // token and logout can clear it. Harmless on other calls (server ignores it).
  const response = await fetch(url, { ...init, headers: h, credentials: "include" });

  // Auto-refresh on a single 401, but only for authenticated calls and
  // only once per call (``allowRefresh`` guards the recursion). The refresh
  // itself will fail fast if no valid cookie is present.
  if (response.status === 401 && allowRefresh && !anonymous && !path.includes("/auth/refresh")) {
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

export const apiGet = <T>(path: string, options?: RequestOptions) => api<T>(path, options);
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
export const apiPut = <T>(path: string, body: unknown, headers?: HeadersInit) =>
  api<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
    ...(headers ? { headers } : {}),
  });
export const apiDelete = (path: string) => api<void>(path, { method: "DELETE" });
