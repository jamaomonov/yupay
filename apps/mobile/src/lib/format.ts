/**
 * Money and text formatting shared by the screens. Plain TS, unit-tested.
 */

/** Whole soʻm with thin grouping: "61264.000000" → "61 264". */
export function formatSum(amount: string | number): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return "—";
  const whole = Math.round(value).toString();
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** Fill `{name}` placeholders; an unknown placeholder is left as written. */
export function fill(template: string, vars: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}
