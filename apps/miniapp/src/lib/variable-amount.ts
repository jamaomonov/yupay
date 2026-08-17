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

/* ---------------------------------------------------------------------------
 * Amounts typed in something other than dollars.
 *
 * The Steam wallet is bought in dollars, so the number the customer types is
 * the number that gets billed. Telegram Stars is bought in stars at about
 * $0.0155 each — asking for dollars would be asking the customer to do
 * arithmetic this page can do. The SKU carries `amount_unit` ("stars") and
 * `units_per_usd` (64.705882); everything below converts between the two.
 *
 * Dollars stay authoritative on the wire: `toUsd` is what checkout sends, and
 * the server snaps it back to a whole unit before pricing, so the count the
 * customer saw and the count the supplier is sent cannot drift.
 * ------------------------------------------------------------------------- */

/** How many units one dollar buys, or `null` when the SKU is priced in dollars. */
export function unitsPerUsd(sku: {
  units_per_usd?: string | null;
  amount_unit?: string | null;
}): number | null {
  if (!sku.amount_unit || sku.units_per_usd == null) return null;
  const n = Number.parseFloat(sku.units_per_usd);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** A unit count as the dollar amount to send. Six decimals matches the
 *  column; the server snaps to a whole unit regardless. */
export function toUsd(units: number, perUsd: number): number {
  return Number((units / perUsd).toFixed(6));
}

/** A dollar bound as a whole number of units, rounded inward so the displayed
 *  range never promises an amount the server would reject: a minimum rounds up
 *  and a maximum rounds down. */
export function boundToUnits(usd: number, perUsd: number, edge: "min" | "max"): number {
  const raw = usd * perUsd;
  return edge === "min" ? Math.ceil(raw - EPSILON) : Math.floor(raw + EPSILON);
}

/** Whether a typed unit count can be charged. Units are whole things — half a
 *  star does not exist — so any fraction is a precision error. */
export function unitAmountError(units: number, min: number, max: number): AmountErrorReason {
  if (Math.abs(units - Math.round(units)) > EPSILON) return "precision";
  if (units < min) return "below";
  if (units > max) return "above";
  return null;
}

/** One package, as the free-amount field needs to see it: how many units it
 *  delivers and what it costs in the currency being shown. */
export interface PricedPack {
  units: number;
  /** Price in the displayed currency — already an override or an FX
   *  conversion, whichever the API resolved. */
  price: number;
}

/**
 * What a typed amount costs, priced from the packages.
 *
 * Margin differs per pack (20% on the small ones, less on the large), so there
 * is no single rate that prices "any amount" — the amount is priced from the
 * pack it falls in, and the two can then never disagree. Mirrors
 * `orders.service.tier_price_usd`, which is what actually charges; this is the
 * same rule so the page shows what the server will bill.
 *
 * Deliberately works in the **displayed** currency rather than USD: a pack may
 * carry a per-currency override, and reading its resolved price is what makes
 * the field follow that too.
 *
 * Two rules, and the second is easy to miss: the band is the largest pack at or
 * below the amount, and the amount never costs more than the next pack up —
 * without the cap, 499 stars priced at the 100-pack's rate cost more than the
 * 500 pack, so buying less cost more. Returns `null` below the smallest pack
 * rather than inventing a price.
 */
export function tierPrice(units: number, packs: readonly PricedPack[]): number | null {
  const sorted = [...packs]
    .filter((p) => p.units > 0 && p.price > 0)
    .sort((a, b) => a.units - b.units);
  let band: PricedPack | null = null;
  let ceiling: number | null = null;
  for (const pack of sorted) {
    if (pack.units <= units) band = pack;
    else if (ceiling === null) ceiling = pack.price;
  }
  if (band === null) return null;
  const total = units * (band.price / band.units);
  return ceiling !== null && total > ceiling ? ceiling : total;
}
