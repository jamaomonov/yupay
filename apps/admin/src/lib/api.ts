/**
 * HTTP client for the admin SPA.
 *
 * Reads/writes the access JWT from/to localStorage, attaches it as a Bearer header,
 * and surfaces 401/403/non-2xx as typed exceptions so the UI can react explicitly.
 */

const TOKEN_KEY = "yupay.admin.access_token";
const REFRESH_KEY = "yupay.admin.refresh_token";

const apiBase = (import.meta.env.VITE_API_BASE_URL) ?? "";

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

export async function api<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
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
export const apiPost = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const apiPatch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const apiDelete = (path: string) => api<void>(path, { method: "DELETE" });
