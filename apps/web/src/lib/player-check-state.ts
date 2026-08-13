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
