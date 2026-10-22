/**
 * What a push carries, read safely. Plain TS, unit-tested; the rest is `push.ts`.
 */

/** The order a tapped push points at, or `null`. */
export function orderOf(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const { type, order_id: orderId } = data as { type?: unknown; order_id?: unknown };
  return type === "order" && typeof orderId === "string" && orderId !== "" ? orderId : null;
}
