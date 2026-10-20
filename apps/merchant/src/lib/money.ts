/**
 * Money arithmetic for the order summary.
 *
 * In cents, as integers. The API sends decimal **strings** precisely so a
 * price never passes through a float, and a browser that parsed them back into
 * doubles to show "deposit after" would reintroduce the problem one layer
 * later — $0.1 + $0.2 is not $0.3 in IEEE-754, and a reseller comparing our
 * arithmetic to their own would find us wrong by a cent.
 *
 * The unit price of a unit SKU carries six decimals, so the multiplication
 * happens in micro-dollars and rounds to the cent **once**, which is the same
 * rule `merchants.pricing.merchant_order_total` applies on the server. Both
 * sides therefore compute the same total from the same published number, and
 * `expected_price` matches.
 */

const CENTS = 100n;
const MICROS = 1_000_000n;

/** Parse a decimal string into scaled integer units. */
function scaled(value: string, scale: bigint): bigint {
  const [whole = "0", fraction = ""] = value.trim().split(".");
  const digits = String(scale).length - 1;
  const padded = (fraction + "0".repeat(digits)).slice(0, digits);
  const sign = whole.startsWith("-") ? -1n : 1n;
  return sign * (BigInt(whole.replace("-", "") || "0") * scale + BigInt(padded || "0"));
}

/**
 * Whether a typed amount is a plain non-negative decimal with at most
 * `places` decimals — the only shape `scaled` reads correctly. `BigInt("1,5")`
 * throws, and it ran while rendering, so a decimal comma took the whole
 * cabinet down to its error page; `-5` and `1.005` went on to a request the
 * server had to refuse.
 */
export function isPlainDecimal(value: string, places: number): boolean {
  const pattern = places === 0 ? /^\d+$/ : new RegExp(`^\\d+(\\.\\d{1,${String(places)}})?$`);
  return pattern.test(value.trim());
}

export function toCents(value: string): bigint {
  return scaled(value, CENTS);
}

export function formatUsd(cents: bigint): string {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const whole = absolute / CENTS;
  const rest = absolute % CENTS;
  return `${negative ? "-" : ""}${whole}.${String(rest).padStart(2, "0")}`;
}

/**
 * Dollars as a reseller reads them: `$1284.37` (no grouping, like the rest of the cabinet), and a debit as `−$0.88` (a real minus, before the sign), never the
 * `$-0.88` that string-gluing «$» onto a signed number produced.
 */
export function dollars(cents: bigint): string {
  return cents < 0n ? `−$${formatUsd(-cents)}` : `$${formatUsd(cents)}`;
}

/** Round a micro-dollar amount up to the cent — the server's rule, once. */
function ceilToCent(micros: bigint): bigint {
  const per = MICROS / CENTS;
  return (micros + per - 1n) / per;
}

/** The order total for a fixed SKU: its own price. */
export function fixedTotal(price: string): bigint {
  return toCents(price);
}

/** The order total for a unit or amount SKU: `ceil_to_cent(unit × count)`. */
export function scaledTotal(unitPrice: string, count: string): bigint {
  const unit = scaled(unitPrice, MICROS);
  const [whole = "0", fraction = ""] = count.trim().split(".");
  const quantity = scaled(`${whole}.${fraction}`, MICROS);
  return ceilToCent((unit * quantity) / MICROS);
}

/**
 * A price string as a reseller reads it: the API pads decimals (`1.020000`), so trailing
 * zeros go — down to cents, never below. A price under a cent (a Star) keeps its digits.
 */
export function formatPrice(value: string): string {
  const [whole = "0", fraction = ""] = value.split(".");
  const trimmed = fraction.replace(/0+$/, "");
  return `${whole}.${trimmed.padEnd(2, "0")}`;
}

/**
 * A unit price under ten cents, read per hundred: a Star at `$0.015576` is `$1.5576` for 100 —
 * six decimals on a price list read as noise, and nobody buys one Star. Exact: the decimal
 * point moves, nothing is rounded. `null` from ten cents up.
 */
export function perHundred(unitPrice: string): string | null {
  if (scaled(unitPrice, MICROS) >= MICROS / 10n) return null;
  const [whole = "0", fraction = ""] = unitPrice.split(".");
  const digits = (fraction + "00").slice(0, 2);
  const rest = fraction.slice(2);
  const head = `${whole === "0" ? "" : whole}${digits}`.replace(/^0+(?=\d)/, "");
  return formatPrice(`${head || "0"}.${rest}`);
}
