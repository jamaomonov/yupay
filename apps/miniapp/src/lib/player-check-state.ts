/**
 * Framework-agnostic state + orchestration for the storefront player check.
 * Kept out of the React component so it is unit-testable in the node env
 * (the app has no jsdom/testing-library). The component is thin glue over this.
 */
import { checkPlayer, type PlayerCheckResult } from "@/lib/player-check";

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
): Promise<PlayerCheckResult> {
  try {
    return await run(productId, input);
  } catch {
    // A thrown fetch (network, our 5xx, 429) is our/provider fault, not the
    // customer's — surface it as `error`, never `invalid`.
    return { status: "error", name: null };
  }
}

/** The bit of a `FormField` this module needs: its key, and whether its
 *  `check` names a sibling server field. Structural rather than importing
 *  `FormField` from `@/lib/catalog`, so this stays a leaf module. */
interface CheckableField {
  key: string;
  check?: { server_field?: string | null } | null | undefined;
}

/**
 * One check outcome, kept together with the question it answers.
 *
 * The lookup is scoped to a product, an id and the server that id lives on,
 * so the answer is only ever about that triple. Two of the three are easy to
 * forget:
 *
 * - the **product**, because a game sold per account region (ADR-0048) is one
 *   product per region, and switching package switches product while keeping
 *   the typed id;
 * - the **server**, because G2B resolves a player *on a server* and the form
 *   leaves that field editable next to the confirmed id.
 *
 * Either way the customer would be looking at a green pill vouching for an
 * account nobody asked about.
 */
export interface PlayerCheckVerdict {
  productId: string;
  /** The id exactly as it was sent — not trimmed, not normalized, so the
   *  verdict answers for the literal text the field held. */
  playerId: string;
  /** The sibling server field's value as it was sent, or `null` when this
   *  field's `check` names no sibling. */
  serverId: string | null;
  result: PlayerCheckResult;
}

/** The sibling server field's current value for a checkable field, or `null`
 *  when its `check` names no sibling. One expression, so the value the check
 *  is *asked* with and the value it is *read back* against cannot drift. */
export function serverIdFor(field: CheckableField, values: Record<string, string>): string | null {
  return field.check?.server_field ? (values[field.check.server_field] ?? null) : null;
}

/**
 * The verdict that currently applies to this exact question, or `null` when
 * none does.
 *
 * Derived at render, from the one stored verdict, by every reader — so the
 * pill, the "continue" gate and the review screen's nickname cannot disagree
 * inside a commit. It used to be a `setState(IDLE)` in one passive effect
 * mirrored up to the page by a second: passive effects flush in a later
 * scheduler task, so the commit that switched product still painted the green
 * pill for the *other* region while the page still held its `valid` and the
 * CTA stayed live. Fail-open, in the one direction the gate exists for.
 *
 * It also settles the late answer: a check that lands after the customer has
 * retyped is filed under what was asked, so it is simply never read back.
 *
 * Compared verbatim, with no canonicalisation, deliberately unlike
 * `gift-profile.ts::profileCheckState`: dropping a verdict here lands on
 * `null`, which `blocksCheckout` also blocks on, so an over-eager drop costs
 * a second «Проверить» and nothing else. There, `null` is permissive and
 * `not_found` is the blocking verdict, so it would clear the one answer that
 * blocks a purchase.
 */
export function currentCheck(
  verdict: PlayerCheckVerdict | null | undefined,
  productId: string,
  playerId: string,
  serverId: string | null,
): PlayerCheckResult | null {
  if (verdict == null) return null;
  return verdict.productId === productId &&
    verdict.playerId === playerId &&
    verdict.serverId === serverId
    ? verdict.result
    : null;
}

/**
 * The verdict standing behind one checkable field right now, given everything
 * the page holds.
 *
 * The whole decision in one pure function on purpose: `TopUp` reads it twice
 * — once to gate the CTA (`blocksCheckout`), once for the nickname on the
 * review screen — and `DynamicFields` reads it a third time to draw the pill.
 * Three hand-written derivations of "is this still the answer" is how a panel
 * and its field start disagreeing about whose account is being topped up.
 * Pulled out pure so the matrix is unit-testable without rendering (this app's
 * Vitest suite is node-env, no jsdom/RTL), mirroring `walletPayState` and
 * `profileCheckState`.
 *
 * `null` for a field with no `check` config: nothing was ever asked, so there
 * is nothing to stand behind it.
 */
export function currentFieldCheck(
  verdicts: Record<string, PlayerCheckVerdict | null>,
  productId: string,
  values: Record<string, string>,
  field: CheckableField,
): PlayerCheckResult | null {
  if (!field.check) return null;
  return currentCheck(
    verdicts[field.key],
    productId,
    values[field.key] ?? "",
    serverIdFor(field, values),
  );
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
