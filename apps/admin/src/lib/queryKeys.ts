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
  category: (id: string) => ["admin", "categories", id] as const,
  brands: () => ["admin", "brands"] as const,
  brand: (id: string) => ["admin", "brands", id] as const,
  products: (filters?: { brandId?: string | null }) =>
    ["admin", "products", filters?.brandId ?? null] as const,
  product: (id: string) => ["admin", "products", id] as const,
  skus: (filters?: { productId?: string | null }) =>
    ["admin", "skus", filters?.productId ?? null] as const,
  sku: (id: string) => ["admin", "skus", id] as const,

  // inventory
  inventoryCounts: (skuId: string) =>
    ["admin", "inventory", "counts", skuId] as const,
  inventoryCodes: (filters: { skuId?: string | null; state?: string | null }) =>
    [
      "admin",
      "inventory",
      "codes",
      filters.skuId ?? null,
      filters.state ?? null,
    ] as const,

  // sourcing
  sourcingRules: () => ["admin", "sourcing", "rules"] as const,
  sourcingDecision: (skuId: string) =>
    ["admin", "sourcing", "decision", skuId] as const,

  // orders
  orders: (filters: { status?: string | null }) =>
    ["admin", "orders", filters.status ?? null] as const,
  order: (id: string) => ["admin", "orders", id] as const,

  // users
  users: (filters: { search?: string | null; limit?: number; offset?: number }) =>
    [
      "admin",
      "users",
      filters.search ?? null,
      filters.limit ?? 50,
      filters.offset ?? 0,
    ] as const,
  user: (id: string) => ["admin", "users", id] as const,

  // fx
  fxRates: () => ["admin", "fx", "rates"] as const,

  // webhook log
  webhooks: (filters: {
    provider?: string | null;
    signature_ok?: boolean | null;
  }) =>
    [
      "admin",
      "webhooks",
      filters.provider ?? null,
      filters.signature_ok ?? null,
    ] as const,

  // audit feed
  audit: (filters: {
    sources?: string[] | null;
    actor?: string | null;
    target?: string | null;
    since?: string | null;
    until?: string | null;
  }) =>
    [
      "admin",
      "audit",
      filters.sources ?? null,
      filters.actor ?? null,
      filters.target ?? null,
      filters.since ?? null,
      filters.until ?? null,
    ] as const,

  // stats
  dashboard: (windowHours: number) =>
    ["admin", "stats", "dashboard", windowHours] as const,

  // wallet
  walletUser: (userId: string) => ["admin", "wallet", "user", userId] as const,

  // fulfillment
  fulfillmentTasks: (filters: {
    orderId?: string | null;
    supplier?: string | null;
    status?: string | null;
  }) =>
    [
      "admin",
      "fulfillment",
      "tasks",
      filters.orderId ?? null,
      filters.supplier ?? null,
      filters.status ?? null,
    ] as const,
  fulfillmentTask: (taskId: string) =>
    ["admin", "fulfillment", "task", taskId] as const,
  // Manual-fulfilment queue — same backend listing as fulfillmentTasks
  // but with the supplier/status filters frozen on the page level, so
  // it deserves its own key for clean invalidation.
  manualQueue: () => ["admin", "manual-fulfillment", "queue"] as const,

  // payments
  payments: (filters: {
    orderId?: string | null;
    provider?: string | null;
    status?: string | null;
  }) =>
    [
      "admin",
      "payments",
      filters.orderId ?? null,
      filters.provider ?? null,
      filters.status ?? null,
    ] as const,
  payment: (id: string) => ["admin", "payments", id] as const,
};
