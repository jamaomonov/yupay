/**
 * API client factory.
 *
 * Both `apps/web` and `apps/miniapp` import {@link createApiClient}; they differ only in
 * the `auth` strategy (Bearer / Guest / Telegram initData).
 */

export interface ApiClientOptions {
  /** Absolute base URL of the API, e.g. `https://api.yupay.uz`. */
  baseUrl: string;
  /** Optional getter returning the current `Authorization` header value. */
  getAuthHeader?: () => string | undefined;
  /** Optional preferred locale (used for `Accept-Language`). */
  getLocale?: () => string | undefined;
}

export interface ApiClient {
  baseUrl: string;
  request: <T = unknown>(path: string, init?: RequestInit) => Promise<T>;
}

export function createApiClient(opts: ApiClientOptions): ApiClient {
  const baseUrl = opts.baseUrl.replace(/\/+$/, "");

  return {
    baseUrl,
    async request<T>(path: string, init?: RequestInit): Promise<T> {
      const url = path.startsWith("http") ? path : `${baseUrl}${path}`;
      const headers = new Headers(init?.headers);
      headers.set("Accept", "application/json");
      const auth = opts.getAuthHeader?.();
      if (auth && !headers.has("Authorization")) headers.set("Authorization", auth);
      const locale = opts.getLocale?.();
      if (locale && !headers.has("Accept-Language")) headers.set("Accept-Language", locale);

      const response = await fetch(url, { ...init, headers });
      if (!response.ok) {
        const body = await response.text();
        throw new ApiError(response.status, response.statusText, body);
      }
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    },
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string,
  ) {
    super(`${status.toString()} ${statusText}: ${body}`);
    this.name = "ApiError";
  }
}
