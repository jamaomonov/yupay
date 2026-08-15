/**
 * Shared money formatter for the admin SPA.
 *
 * Backend amounts (orders, payments, wallet ledger) are ``Decimal`` values
 * serialized as high-precision strings — ``NUMERIC(20, 6)`` columns, e.g.
 * ``"12919.969152"`` or ``"5000.000000"``. They are already **major units**
 * (sum / dollars), never minor units (tiyin / cents) — do not divide by 100.
 *
 * Displaying that raw precision to an operator is never correct: UZS and RUB
 * are effectively zero-decimal currencies in every customer- and
 * operator-facing surface (nobody prices things in tiyin/kopeck), while USD
 * and USDT keep the conventional 2 decimals. This module is the single
 * source of truth for "how many decimals does this currency show" — no
 * other file should call `.toFixed()` / `.toLocaleString()` on a money value
 * directly.
 *
 * The global search sublabel used to pre-format amounts server-side (with a
 * duplicate decimals table) — it now sends the raw `amount` + `currency` and
 * the admin SPA formats them through `formatMoney` here, same as every other
 * surface (see `features/search/SearchPalette.tsx`).
 */

const CURRENCY_DECIMALS: Record<string, number> = {
  UZS: 0,
  RUB: 0,
  USD: 2,
  USDT: 2,
};

const DEFAULT_DECIMALS = 2;

function decimalsFor(currency: string): number {
  return CURRENCY_DECIMALS[currency.toUpperCase()] ?? DEFAULT_DECIMALS;
}

/**
 * Format a bare money amount (no currency suffix) — grouped with ru-RU
 * separators, rounded to the currency's canonical decimal count. Use this
 * when the currency is rendered separately (e.g. its own table column) or
 * needs a custom prefix/sign (``$``, ``+``/``−``).
 */
export function formatMoneyValue(amount: string | number, currency: string): string {
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  const decimals = decimalsFor(currency);
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

/**
 * Format a money amount with its currency code, e.g. ``"12 920 UZS"`` or
 * ``"1.00 USD"``. This is the default — use it everywhere an amount and its
 * currency are shown together.
 */
export function formatMoney(amount: string | number, currency: string): string {
  return `${formatMoneyValue(amount, currency)} ${currency}`;
}

/** Matches the grouping separator `Intl.NumberFormat("ru-RU")` itself uses
 *  (U+00A0, not a plain space) — see `formatMoneyValue` above — so a money
 *  input reads identically to a settled money display right next to it. */
const GROUP_SEPARATOR = " ";

/**
 * Group the integer-part digits of an amount an operator is *mid-typing*,
 * e.g. ``"12000000"`` → ``"12 000 000"``. Unlike `formatMoneyValue`, this
 * formats whatever has been typed so far — a bare sign, a trailing decimal
 * point, an empty string — without forcing a fixed decimal count or a
 * canonical separator, so it's safe to run on every keystroke of a money
 * input (see `MoneyInput`). The decimal separator and fractional digits, if
 * any, pass through untouched: existing parsers (`parseAdjustAmount`, the
 * price-override schema) already accept both `,` and `.`.
 */
export function groupAmountInput(raw: string): string {
  const sign = raw.startsWith("-") ? "-" : "";
  const unsigned = sign ? raw.slice(1) : raw;
  const sepIndex = unsigned.search(/[.,]/);
  const intPart = sepIndex === -1 ? unsigned : unsigned.slice(0, sepIndex);
  const tail = sepIndex === -1 ? "" : unsigned.slice(sepIndex);
  const digits = intPart.replace(/\D/g, "");
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP_SEPARATOR);
  return `${sign}${grouped}${tail}`;
}

/**
 * Inverse of `groupAmountInput` — strips the grouping whitespace an operator
 * may have typed (or that live-formatting inserted), leaving the raw string
 * existing parsers already expect. `\s` covers the NBSP/narrow-NBSP variants
 * alongside a plain space.
 */
export function ungroupAmountInput(display: string): string {
  return display.replace(/\s/g, "");
}
