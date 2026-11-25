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

/**
 * A gate shared by every caller in this server process: at most `limit` of the
 * functions passed to it run at once, the rest wait in arrival order.
 *
 * `mapLimit` caps one page. It did not cap the storefront: when the cached
 * region data expired, a crawler walking the region pages started dozens of
 * regenerations together, each with its own three fetches — ~280 brand and
 * ~280 product calls in one minute against the single API process, p95 2–9 s,
 * ApiHighLatency firing again (2026-11-25). A module-level gate caps them all.
 */
export function createGate(limit: number): <R>(fn: () => Promise<R>) => Promise<R> {
  let running = 0;
  const waiting: (() => void)[] = [];
  return async <R>(fn: () => Promise<R>): Promise<R> => {
    if (running >= limit) await new Promise<void>((resolve) => waiting.push(resolve));
    else running += 1;
    try {
      return await fn();
    } finally {
      const wake = waiting.shift();
      // Hand the slot straight to the next waiter; free it only when none wait.
      if (wake) wake();
      else running -= 1;
    }
  };
}
