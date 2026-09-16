/**
 * Framework-agnostic state + orchestration for the storefront player check.
 * Kept out of the React component so it is unit-testable in the node env
 * (the app has no jsdom/testing-library). The component is thin glue over this.
 */
import { checkPlayer, type PlayerCheckResult } from "@/lib/player-check";

/** Why the check cannot run yet, or `null` when it can.
 *
 * Named rather than boolean so the UI can say what to do instead of just
 * dimming a button — a check that silently refuses to fire reads as broken.
 */
export type CheckBlocker = "playerId" | "serverId";

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
 * Used to check a `product` blocker first: a brand that sold the same game
 * per region (Mobile Legends: global vs RU) modeled that as one product per
 * region, and running the lookup against an arbitrary one before a package
 * was picked answered "no such player" for a perfectly good id. ADR-0079
 * retired that shape — a region split is two brands now, and a brand is
 * exactly one game, so every product on a brand's page shares the one game
 * the check is scoped to. There is nothing left a package choice could
 * change about which account is checked, so nothing here blocks on it.
 */
export function checkBlocker(input: {
  value: string;
  // `| undefined` spelled out on every optional: `exactOptionalPropertyTypes`
  // is on, so `?:` alone means "absent", not "may be undefined", and callers
  // forward values that genuinely can be.
  pattern?: string | null | undefined;
  server?: { required: boolean; id: string | null | undefined } | null | undefined;
}): CheckBlocker | null {
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
  brandSlug: string,
  input: { playerId: string; serverId?: string | null },
  run: typeof checkPlayer = checkPlayer,
): Promise<PlayerCheckResult> {
  try {
    return await run(brandSlug, input);
  } catch {
    // A thrown fetch (network, our 5xx, 429) is our/provider fault, not the
    // customer's — surface it as `error`, never `invalid`.
    return { status: "error", name: null };
  }
}

/**
 * One check outcome, kept together with the question it answers.
 *
 * The lookup is scoped to a brand and an id, so the answer is only ever about
 * that pair — a brand is exactly one supplier game (ADR-0079), so every
 * product on a brand's page shares one verdict and G2B answers about the game
 * it was asked.
 *
 * `serverId` is part of it too, and has to be: G2B is asked for the id *on a
 * server*, and an id-only lookup against the wrong one just answers "no such
 * player". On MLBB the id collapses into the confirmation pill but the server
 * stays an ordinary editable field beside it, so without this a buyer verifies
 * 1313232551 on 6618, changes the server to 7001, and pays for a
 * `{player_id, server}` pair nobody ever checked — which the API's own
 * validation cannot catch either, since it checks each field alone (2026-09-04
 * review round 1).
 */
export interface PlayerCheckVerdict {
  /** The brand the lookup was scoped to — one game, so one verdict per brand. */
  brandSlug: string;
  /** The id exactly as it was sent — not trimmed, not normalized, so the
   *  verdict answers for the literal text the field held. */
  playerId: string;
  /** The sibling server field's value as it was sent, or `null` when this
   *  field's `check` names no sibling. */
  serverId: string | null;
  result: PlayerCheckResult;
}

/**
 * The verdict that currently applies to this exact question — the id, the
 * server it was asked on, and the brand it was scoped to — or `null` when
 * none does.
 *
 * Derived at render — by the field that draws the confirmation pill and by the
 * panel that gates Pay on it, from the one stored verdict — so the two cannot
 * disagree inside a commit. It used to be a `setState(IDLE)` in one passive
 * effect, mirrored up to the panel by a second: switching to another region's
 * package left a commit (two, counting the mirror re-reporting the old value)
 * showing a nickname verified against the *other* product while Pay was still
 * enabled. Reading the stored answer back through the pair it was asked about
 * makes going stale a property of this render rather than of an effect that
 * has yet to run. Keyed by brand (ADR-0079) rather than product, so that
 * switching packages inside a brand — the case the region split used to
 * confuse with a game switch — no longer trips this at all.
 *
 * It also settles the late answer: a check that lands after the customer has
 * retyped is filed under what was asked, so it is simply never read back —
 * the same thing `gift-invite.ts::currentVerdict` does with `canonicalUrl`.
 *
 * Compared verbatim, with no canonicalisation, and that is deliberate here
 * where the gift flow does the opposite: dropping a verdict lands on `null`,
 * which `blocksCheckout` also blocks on, so a cosmetic edit costs the buyer a
 * second «Проверить» and nothing else. In the gift flow the blocking verdict
 * is `not_found` and `null` is permissive, so an over-eager drop would clear
 * the one answer that blocks a purchase.
 */
export function currentCheck(
  verdict: PlayerCheckVerdict | null | undefined,
  brandSlug: string,
  playerId: string,
  serverId: string | null,
): PlayerCheckResult | null {
  if (verdict == null) return null;
  return verdict.brandSlug === brandSlug &&
    verdict.playerId === playerId &&
    verdict.serverId === serverId
    ? verdict.result
    : null;
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
