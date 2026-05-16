/**
 * Centralised TanStack Query keys.
 *
 * Co-located so cache invalidation never relies on stringly-typed keys spread across
 * the codebase. Each top-level constant is a function returning a tuple — TanStack's
 * documented best practice.
 */

export const qk = {
  me: () => ["me"] as const,
  categories: () => ["admin", "categories"] as const,
  brands: () => ["admin", "brands"] as const,
  brand: (id: string) => ["admin", "brands", id] as const,
  products: (filters?: { brandId?: string | null }) =>
    ["admin", "products", filters?.brandId ?? null] as const,
  product: (id: string) => ["admin", "products", id] as const,
  skus: (filters?: { productId?: string | null }) =>
    ["admin", "skus", filters?.productId ?? null] as const,
  sku: (id: string) => ["admin", "skus", id] as const,
};
