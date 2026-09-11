/**
 * Thin fetch wrapper for the YuPay API.
 *
 * Attaches the access JWT (when present) as ``Authorization: Bearer …``.
 * Surfaces 4xx/5xx as typed exceptions so query hooks can react explicitly.
 */

import { getActiveLocale } from "./i18n/core";

const TOKEN_KEY = "yupay.miniapp.access_token";
// Legacy key: the refresh token used to be stored here. Purged on clearTokens so
// a pre-cookie session can't leave a JS-readable 30-day token behind. The refresh
// token now rides an HttpOnly cookie the browser sends automatically.
const LEGACY_REFRESH_KEY = "yupay.miniapp.refresh_token";

export const apiBase =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: unknown,
  ) {
    super(`${status.toString()} ${statusText}`);
    this.name = "ApiError";
  }

  get detail(): string {
    if (this.body && typeof this.body === "object") {
      const b = this.body as { detail?: string; title?: string };
      if (typeof b.detail === "string") return b.detail;
      if (typeof b.title === "string") return b.title;
    }
    return this.message;
  }

  /** RFC 7807 `type` URI from the problem+json body (e.g.
   *  `https://app.yupay.uz/errors/payment-unavailable-abroad`), when the
   *  body was parseable JSON with a `type` string. `undefined` for a
   *  non-JSON body or one without a `type` field — mirrors the web
   *  client's `ApiError.type` (`apps/web/src/lib/client.ts`). */
  get type(): string | undefined {
    if (this.body && typeof this.body === "object" && "type" in this.body) {
      const raw = (this.body as { type?: unknown }).type;
      return typeof raw === "string" ? raw : undefined;
    }
    return undefined;
  }
}

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, access);
  } catch {
    // localStorage may be blocked in some Telegram clients; ignore.
  }
}

export function clearTokens(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(LEGACY_REFRESH_KEY);
  } catch {
    // ignored
  }
}

export interface RequestOptions extends RequestInit {
  /** Suppress the Authorization header even if a token is stored. */
  anonymous?: boolean;
  /** Adds an Idempotency-Key header (required by all write endpoints in v1). */
  idempotencyKey?: string;
}

interface RawTokensOut {
  access_token: string;
}

let refreshInFlight: Promise<string | null> | null = null;

async function tryRefreshOnce(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const url = `${apiBase}/api/v1/auth/refresh`;
      // The refresh token rides an HttpOnly cookie; `credentials: "include"` sends
      // it and stores the rotated one. No token in the request body.
      const resp = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) {
        // Refresh itself failed — wipe so the user can re-auth via initData.
        if (resp.status === 401 || resp.status === 403) clearTokens();
        return null;
      }
      const tokens = (await resp.json()) as RawTokensOut;
      setTokens(tokens.access_token);
      return tokens.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { anonymous, idempotencyKey, headers, ...init } = options;
  const url = path.startsWith("http") ? path : `${apiBase}${path}`;

  const send = async (token: string | null): Promise<Response> => {
    const h = new Headers(headers);
    h.set("Accept", "application/json");
    // Lets an order record which surface placed it (see the web client's
    // SURFACE note). Advisory — the server gates nothing on this.
    h.set("X-Yupay-Surface", "miniapp");
    // Catalog endpoints localize their text from this header (default ru).
    if (!h.has("Accept-Language")) h.set("Accept-Language", getActiveLocale());
    if (init.body && !h.has("Content-Type")) {
      h.set("Content-Type", "application/json");
    }
    if (!anonymous && token) h.set("Authorization", `Bearer ${token}`);
    if (idempotencyKey) h.set("Idempotency-Key", idempotencyKey);
    // Send the auth cookie so telegram-login/refresh can set/rotate the HttpOnly
    // refresh token and logout can clear it. Harmless on other calls.
    return fetch(url, { ...init, headers: h, credentials: "include" });
  };

  let response = await send(anonymous ? null : getAccessToken());

  // Rotate-and-retry once on 401 for authenticated requests when a refresh
  // token is available. Single retry only — never loop.
  if (
    response.status === 401 &&
    !anonymous &&
    path !== "/api/v1/auth/refresh" &&
    path !== "/api/v1/auth/telegram/webapp"
  ) {
    const fresh = await tryRefreshOnce();
    if (fresh) {
      response = await send(fresh);
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

export const apiGet = <T>(path: string, anonymous = false) => api<T>(path, { anonymous });
export const apiPost = <T>(
  path: string,
  body: unknown,
  opts: Omit<RequestOptions, "method" | "body"> = {},
) => api<T>(path, { ...opts, method: "POST", body: JSON.stringify(body) });
export const apiPatch = <T>(
  path: string,
  body: unknown,
  opts: Omit<RequestOptions, "method" | "body"> = {},
) => api<T>(path, { ...opts, method: "PATCH", body: JSON.stringify(body) });
export const apiDelete = (path: string) => api<void>(path, { method: "DELETE" });

/** Generate a random idempotency key suitable for the backend's >=16 char rule. */
export function newIdempotencyKey(prefix = "miniapp"): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `${prefix}-${rand}`;
}
