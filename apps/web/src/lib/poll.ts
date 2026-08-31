/**
 * How often to poll an order while the realtime socket is down.
 *
 * This fallback switches on precisely when the socket drops, and the socket
 * drops precisely when the API is struggling — so a flat, short interval turns
 * a degraded API into a busier one. At the previous 4s, a hundred customers
 * waiting on an order were ~25 req/s of pure polling on the order query alone,
 * arriving exactly when there was no capacity for it. That is a positive
 * feedback loop, not a fallback.
 *
 * Three properties, each doing a different job:
 *
 * - a longer base, so the crowd costs less;
 * - backoff on consecutive failures, so a client stops knocking at the same
 *   rate at an API that is already refusing;
 * - jitter, so clients that dropped together do not retry together. Without
 *   it the herd stays a herd for as long as the outage lasts.
 *
 * The cap matters too: past it, a recovered API would not be noticed for
 * minutes, and the customer is sitting on an order page waiting for a code.
 */
const BASE_MS = 8_000;
const MAX_MS = 60_000;

/**
 * @param failures consecutive failed fetches, from TanStack's
 *   `query.state.fetchFailureCount`.
 * @returns milliseconds until the next poll.
 */
export function pollInterval(failures = 0): number {
  const backoff = Math.min(BASE_MS * 2 ** Math.min(failures, 3), MAX_MS);
  // Capped after jittering, not before — otherwise the jitter walks straight
  // back through the ceiling it is meant to respect.
  return Math.min(Math.round(backoff * (1 + Math.random())), MAX_MS);
}

/** Statuses during which the order page keeps itself fresh. */
const IN_MOTION = new Set(["pending_payment", "paid", "fulfilling", "fulfilled"]);

/**
 * Refetch interval for the order query on the order page.
 *
 * A live socket silences polling only for ``pending_payment`` — that state
 * can sit for hours and its exit is user-driven. Through
 * ``paid → fulfilling → fulfilled`` (the delivery window) the page polls even
 * while the socket says connected: a backgrounded tab or a WebView suspended
 * during the payment hop leaves a zombie socket that still reports connected,
 * and the delivered push dies in it — the poll is the reconciler, the socket
 * only the accelerator, mirroring the worker's NOTIFY-plus-poll design.
 *
 * @param status current order status, if loaded.
 * @param opts `connected` from the realtime store; `failures` from TanStack's
 *   `query.state.fetchFailureCount`.
 * @returns milliseconds until the next poll, or `false` to stop.
 */
export function orderPollInterval(
  status: string | undefined,
  opts: { connected: boolean; failures?: number },
): number | false {
  if (!status || !IN_MOTION.has(status)) return false;
  if (opts.connected && status === "pending_payment") return false;
  return pollInterval(opts.failures ?? 0);
}
