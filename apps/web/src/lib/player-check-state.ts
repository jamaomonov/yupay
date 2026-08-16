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

/** Why the check cannot run yet, or `null` when it can.
 *
 * Named rather than boolean so the UI can say what to do instead of just
 * dimming a button — a check that silently refuses to fire reads as broken.
 */
export type CheckBlocker = "product" | "playerId" | "serverId";

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
  return checkBlocker({ value, pattern, server }) === null;
}

/**
 * The first thing standing between the customer and a meaningful answer.
 *
 * Order matters, and `product` comes first on purpose: the check is scoped to
 * one product, and a brand that sells the same game per region (Mobile
 * Legends: global vs RU — ADR-0048) has one product per region. Until the
 * buyer picks a package we do not know which, and running the lookup against
 * an arbitrary one answers "no such player" for a perfectly good id — then the
 * FAQ tells them that means they need the *other* region, sending them the
 * wrong way. Filled-in ids cannot fix that, so it is reported before them.
 */
export function checkBlocker(input: {
  value: string;
  // `| undefined` spelled out on every optional: `exactOptionalPropertyTypes`
  // is on, so `?:` alone means "absent", not "may be undefined", and callers
  // forward values that genuinely can be.
  pattern?: string | null | undefined;
  server?: { required: boolean; id: string | null | undefined } | null | undefined;
  /** False only when the brand sells more than one product and none is picked
   *  yet. A single-product brand is never ambiguous, so it never blocks. */
  productChosen?: boolean | undefined;
}): CheckBlocker | null {
  if (input.productChosen === false) return "product";
  const v = input.value.trim();
  if (v.length === 0) return "playerId";
  if (input.pattern) {
    try {
      if (!new RegExp(input.pattern).test(v)) return "playerId";
    } catch {
      // malformed server-supplied pattern must never block the user
    }
  }
  if (input.server?.required && (input.server.id ?? "").trim().length === 0) return "serverId";
  return null;
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
