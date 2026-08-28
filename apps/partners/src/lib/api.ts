/**
 * The browser's way to the API.
 *
 * **This code never holds the refresh token.** It rides an HttpOnly cookie the
 * API sets, so no script on this page — including an injected one — can read a
 * 30-day session that can move money out. The access token lives in memory and
 * dies with the tab.
 *
 * Every call therefore sends credentials, and restoring a session on load is
 * just asking the refresh endpoint what the cookie says.
 *
 * This used to keep the refresh token in `sessionStorage`, because the API
 * returned it in the body and there was nowhere else for it to survive a
 * reload. That was the honest-but-worse arrangement; the API now sets the
 * cookie instead (the same shape the buyer flow has used since ADR-0007).
 */

let accessToken: string | null = null;

/** Where the API lives. Same env var as the storefront's browser client. */
export function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export function setAccessToken(access: string): void {
  accessToken = access;
}

export function clearTokens(): void {
  accessToken = null;
}

export function hasSession(): boolean {
  return accessToken !== null;
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
    // Always: the refresh cookie is the session, and a call that omits it
    // cannot be refreshed.
    credentials: "include",
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
  // No body: the cookie is the token, and the server rotates it in the
  // response. Nothing here can send a token because nothing here has one.
  const res = await send("/api/v1/affiliate/auth/refresh", {
    method: "POST",
    anonymous: true,
  });
  if (!res.ok) {
    clearTokens();
    return false;
  }
  const tokens = (await res.json()) as { access_token: string };
  setAccessToken(tokens.access_token);
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

/**
 * Rebuild a session on load.
 *
 * Nothing is passed in: whether there is a session to restore is a question
 * only the cookie can answer, and only the server can read it.
 */
export async function restore(): Promise<boolean> {
  return refresh();
}
