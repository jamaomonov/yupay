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
