/**
 * How many brands the public catalog carries.
 *
 * Read from the storefront's own catalog endpoint, not from a constant: a
 * number on a landing page that nobody updates becomes a lie at the speed the
 * catalog grows. Cached by the page's `revalidate`, so this is one request an
 * hour and not one per visitor.
 *
 * Returns `null` on any failure, and the landing then renders no count at all.
 * That is deliberate — a fallback number would be indistinguishable from a
 * real one, and this page is a claim about our inventory.
 */

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

interface BrandListResponse {
  items?: unknown[];
}

export async function countBrands(): Promise<number | null> {
  try {
    const response = await fetch(`${API}/api/v1/catalog/brands`, {
      next: { revalidate: 3600 },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as BrandListResponse;
    return Array.isArray(body.items) ? body.items.length : null;
  } catch {
    return null;
  }
}
