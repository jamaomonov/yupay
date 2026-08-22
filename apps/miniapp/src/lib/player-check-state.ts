/**
 * Framework-agnostic state + orchestration for the storefront player check.
 * Kept out of the React component so it is unit-testable in the node env
 * (the app has no jsdom/testing-library). The component is thin glue over this.
 */
import { checkPlayer, type PlayerCheckResult } from "@/lib/player-check";

export type CheckState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "done"; result: PlayerCheckResult };

export const IDLE: CheckState = { phase: "idle" };

/** Whether the check button is enabled: value non-empty and, if a pattern is
 *  provided, the value matches it. A malformed server-supplied pattern must
 *  never block the user, so treat a bad regex as "allow". When the field's
 *  `check.server_field` names a sibling (e.g. MLBB's "server"), G2B needs
 *  both values together — an id-only lookup against the wrong server just
 *  returns a false "not found" — so `server.required` also gates the button
 *  on that sibling being filled in. */
export function canCheck(
  value: string,
  pattern?: string | null,
  server?: { required: boolean; id: string | null | undefined } | null,
): boolean {
  const v = value.trim();
  if (v.length === 0) return false;
  if (pattern) {
    try {
      if (!new RegExp(pattern).test(v)) return false;
    } catch {
      // malformed server-supplied pattern must never block the user
    }
  }
  if (server?.required && (server.id ?? "").trim().length === 0) return false;
  return true;
}

/** Run the check, folding ANY error into an advisory soft-failure (never throws).
 *  `run` is injectable for testing; defaults to the real API wrapper. */
export async function runPlayerCheck(
  productId: string,
  input: { playerId: string; serverId?: string | null },
  run: typeof checkPlayer = checkPlayer,
): Promise<CheckState> {
  try {
    return { phase: "done", result: await run(productId, input) };
  } catch {
    // A thrown fetch (network, our 5xx, 429) is our/provider fault, not the
    // customer's — surface it as `error`, never `invalid`.
    return { phase: "done", result: { status: "error", name: null } };
  }
}

/** Sets `key` to `result` in a check-results map, but returns `prev` itself
 *  (same reference) when nothing actually changed.
 *
 * `DynamicFields` reports a checkable field's outcome from an effect keyed
 * partly on the reporter callback the parent hands it — and that callback is
 * a fresh arrow function every render. Without this guard, mapping that into
 * a plain `{ ...prev, [key]: result }` on every one of those calls would
 * itself trigger the parent's next render, forever. Returning the very same
 * reference when the value is unchanged lets React bail out of the update
 * instead (a `useState` setter skips re-rendering on an `Object.is`-equal
 * result), breaking the cycle. */
export function mergeCheckResult(
  prev: Record<string, PlayerCheckResult | null>,
  key: string,
  result: PlayerCheckResult | null,
): Record<string, PlayerCheckResult | null> {
  const current = prev[key] ?? null;
  const unchanged =
    current === result ||
    (current !== null &&
      result !== null &&
      current.status === result.status &&
      current.name === result.name);
  return unchanged ? prev : { ...prev, [key]: result };
}

/** Whether a check outcome still stands between the customer and Pay.
 *
 * `error` does not. It means our side or the provider failed — that is what
 * `runPlayerCheck` folds a network fault, a 5xx and a 429 into, deliberately
 * refusing to call the id `invalid`. Blocking on it anyway made the sale
 * hostage to G2B's uptime and punished the customer for a fault that was
 * never theirs: with the check enabled on a brand, a supplier outage left the
 * Pay button dead with no way past it.
 *
 * So only `invalid` blocks — the provider positively answering "no such
 * player" — and so does an id that has not been checked at all. On `error`
 * the field says the check is unavailable and asks the customer to re-read
 * what they typed, which is the best either of us can do.
 */
export function blocksCheckout(result: PlayerCheckResult | null | undefined): boolean {
  return result == null || result.status === "invalid";
}

/** True when the check could not run and the customer should re-read the id
 *  themselves. Drives the advisory line under the field. */
export function checkUnavailable(result: PlayerCheckResult | null | undefined): boolean {
  return result?.status === "error";
}
