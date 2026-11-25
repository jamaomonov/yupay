/**
 * `Promise.all(items.map(fn))` with at most `limit` calls in flight.
 *
 * The storefront renders against a single API process: a brand page whose
 * region switcher fetched all 28 Steam Wallet countries at once (plus their
 * products, per locale, on every ISR regeneration) held the API's whole DB pool
 * and pushed every other request — checkout included — past the 1.5 s latency
 * alert (2026-11-25). Results keep the input order.
 */
export async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  async function worker(): Promise<void> {
    while (next < items.length) {
      const i = next++;
      // `i` is in range: it was checked against items.length just above.
      results[i] = await fn(items[i] as T, i);
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker));
  return results;
}
