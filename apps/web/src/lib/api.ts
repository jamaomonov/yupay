/**
 * Server-side fetch helper for the YuPay API. Used by Server Components only —
 * it sends the active locale as Accept-Language (the catalog API localises by
 * that header) and an optional `currency` for FX-converted prices, and leans on
 * Next's fetch cache (revalidate + the "catalog" tag) so the storefront doesn't
 * hammer the API on every request.
 *
 * Base URL: API_INTERNAL_URL (server-to-server, e.g. http://api:8000 in Docker)
 * → NEXT_PUBLIC_API_BASE_URL → http://localhost:8000 for host-dev.
 */
const BASE = (
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
  ) {
    super(`API ${String(status)} on ${path}`);
    this.name = "ApiError";
  }
}

interface GetOpts {
  locale: string;
  currency?: string;
  revalidate?: number;
  tags?: string[];
}

export async function apiGet<T>(path: string, opts: GetOpts): Promise<T> {
  const url = new URL(`${BASE}/api/v1${path}`);
  if (opts.currency) url.searchParams.set("currency", opts.currency);
  const res = await fetch(url.toString(), {
    headers: { "Accept-Language": opts.locale },
    next: { revalidate: opts.revalidate ?? 300, tags: opts.tags ?? ["catalog"] },
  });
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

/** Like apiGet but returns null on 404 (for detail pages that call notFound()). */
export async function apiGetOrNull<T>(path: string, opts: GetOpts): Promise<T | null> {
  try {
    return await apiGet<T>(path, opts);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
