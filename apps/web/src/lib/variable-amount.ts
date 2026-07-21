/**
 * Pure, framework-agnostic helpers for the variable-amount (customer-typed
 * dollar amount) SKU flow — the Steam wallet top-up. Kept out of the React
 * components so it is unit-testable in the node env (this repo has no
 * jsdom/testing-library — see ``player-check-state.ts`` for the same pattern).
 *
 * Mirrored verbatim into ``apps/web/src/lib/variable-amount.ts`` — the two
 * storefronts don't share a workspace package for pure logic (see
 * ``player-check-state.ts`` in each app for the same precedent), so keep both
 * copies in sync when this file changes.
 */

/** Why a parsed amount can't be charged. `null` means it's fine. */
export type AmountErrorReason = "below" | "above" | "precision" | null;

/** At most this many digits after the decimal separator — mirrors the
 *  server's own check (``pricing.variable.validate_amount``). */
const MAX_DECIMALS = 2;

/** Tolerance for float round-off when checking the decimal-digit count. */
const EPSILON = 1e-6;

/**
 * Parse a customer-typed dollar amount. Accepts a dot OR a comma as the
 * decimal separator and surrounding whitespace; rejects everything else
 * (signs, thousands separators, scientific notation, multiple separators,
 * a bare/trailing separator, empty input) by returning `null` rather than
 * guessing at intent. Any number of decimal digits is accepted here —
 * capping at two is `amountError`'s job, not the parser's.
 */
export function parseAmount(input: string): number | null {
  const trimmed = input.trim();
  if (trimmed.length === 0) return null;
  if (!/^\d+([.,]\d+)?$/.test(trimmed)) return null;
  const value = Number.parseFloat(trimmed.replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

/**
 * Whether a parsed amount can be charged: at most `MAX_DECIMALS` decimal
 * places, and within `[min, max]` (both inclusive — a closed interval,
 * mirroring the server's `amount_usd < minimum or amount_usd > maximum`
 * check). Precision is checked before range, same order as the server's
 * `validate_amount`, so an amount that's both over-precise and out of range
 * reports one consistent reason.
 */
export function amountError(amount: number, min: number, max: number): AmountErrorReason {
  const scale = 10 ** MAX_DECIMALS;
  const scaled = amount * scale;
  if (Math.abs(scaled - Math.round(scaled)) > EPSILON) return "precision";
  if (amount < min) return "below";
  if (amount > max) return "above";
  return null;
}
