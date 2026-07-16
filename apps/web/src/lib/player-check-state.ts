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
 *  never block the user, so treat a bad regex as "allow". */
export function canCheck(value: string, pattern?: string | null): boolean {
  const v = value.trim();
  if (v.length === 0) return false;
  if (pattern) {
    try {
      return new RegExp(pattern).test(v);
    } catch {
      return true;
    }
  }
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
    return { phase: "done", result: { valid: false, name: null, reason: null } };
  }
}
