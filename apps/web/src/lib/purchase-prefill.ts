import type { FormField } from "./catalog";

import { parseAmount } from "./variable-amount";

/** What a link may pre-fill on a purchase panel. */
export interface Prefill {
  /** Field values keyed by `FormField.key`, each one its pattern accepts. */
  fields: Record<string, string>;
  /** The typed amount as a string, or `null` when absent or not a number. */
  amount: string | null;
}

/**
 * Reads a hand-off from a link — the home page's Steam form sends
 * `?steam_login=…&amount=…` — into the panel's fields. Only the product's own
 * fields are taken, and only values their pattern accepts; anything else in the
 * query (utm tags, a stray email) is ignored rather than trusted.
 */
export function prefillFromQuery(query: URLSearchParams, fields: FormField[]): Prefill {
  const out: Record<string, string> = {};
  for (const f of fields) {
    const v = query.get(f.key)?.trim();
    if (!v) continue;
    if (f.pattern && !new RegExp(f.pattern).test(v)) continue;
    out[f.key] = v;
  }
  const raw = query.get("amount")?.trim() ?? "";
  return { fields: out, amount: parseAmount(raw) === null ? null : raw };
}
