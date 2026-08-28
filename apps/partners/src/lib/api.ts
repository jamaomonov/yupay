/**
 * The browser's way to the API.
 *
 * **Where the tokens live, stated plainly.** The access token is in memory
 * only. The refresh token is in memory *and* `sessionStorage`, because the API
 * returns it in a response body rather than setting an HttpOnly cookie, so
 * there is nowhere else for it to survive a page reload.
 *
 * `sessionStorage` rather than `localStorage`: it dies when the tab closes and
 * is not shared between tabs, so a partner who walks away from a public
 * machine has a shorter exposure. It is still readable by any script running
 * on this origin — that is the honest cost, and the mitigations are that the
 * token rotates on every use (a stolen one stops working the moment the real
 * partner refreshes) and that the panel loads no third-party script.
 *
 * The proper fix is an HttpOnly refresh cookie, which needs an API change; it
 * is worth doing before this site carries real money at volume.
 */

let accessToken: string | null = null;
let refreshToken: string | null = null;

/** Where the API lives. Same env var as the storefront's browser client. */
export function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export function setTokens(access: string, refresh: string): void {
  accessToken = access;
  refreshToken = refresh;
  persist(refresh);
}

export function clearTokens(): void {
  accessToken = null;
  refreshToken = null;
  persist(null);
}

export function hasSession(): boolean {
  return accessToken !== null;
}

/** The refresh token, for the one caller that needs to send it: sign-out. */
export function currentRefreshToken(): string | null {
  return refreshToken;
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

interface Options {
  method?: string;
  body?: unknown;
  /** Skip the Authorization header — for sign-in and the application form. */
  anonymous?: boolean;
  idempotencyKey?: string;
}

async function send(path: string, opts: Options): Promise<Response> {
  const headers = new Headers({ Accept: "application/json" });
  if (opts.body !== undefined) headers.set("Content-Type", "application/json");
  if (!opts.anonymous && accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (opts.idempotencyKey) headers.set("Idempotency-Key", opts.idempotencyKey);

  return fetch(`${apiBase()}${path}`, {
    method: opts.method ?? "GET",
    headers,
    ...(opts.body === undefined ? {} : { body: JSON.stringify(opts.body) }),
  });
}

/**
 * Exchange the refresh token for a new pair.
 *
 * Returns false when there is nothing to refresh with, or the server refused —
 * a rotated token presented twice, a revoked session, a suspended partner.
 * Either way the caller's answer is the same: sign in again.
 */
async function refresh(): Promise<boolean> {
  if (!refreshToken) return false;
  const res = await send("/api/v1/affiliate/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
    anonymous: true,
  });
  if (!res.ok) {
    clearTokens();
    return false;
  }
  const tokens = (await res.json()) as { access_token: string; refresh_token: string };
  setTokens(tokens.access_token, tokens.refresh_token);
  return true;
}

/**
 * Call the API, refreshing **once** on a 401 and replaying the request.
 *
 * Once, not in a loop: if the replay also comes back 401 the session is gone,
 * and retrying would spend the newly-rotated refresh token on each attempt —
 * turning one expired session into a stream of invalidated ones.
 */
export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  let res = await send(path, opts);

  if (res.status === 401 && !opts.anonymous && (await refresh())) {
    res = await send(path, opts);
  }

  if (!res.ok) {
    if (res.status === 401) clearTokens();
    throw new ApiError(res.status, path);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const STORAGE_KEY = "yupay.partner.refresh";

function persist(token: string | null): void {
  try {
    if (token === null) sessionStorage.removeItem(STORAGE_KEY);
    else sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Private mode, or storage disabled. The session still works for this
    // page; it just will not survive a reload.
  }
}

/** The stored refresh token, if the browser kept one. */
export function storedRefreshToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Rebuild a session on load from the stored refresh token. */
export async function restore(token: string): Promise<boolean> {
  refreshToken = token;
  return refresh();
}
