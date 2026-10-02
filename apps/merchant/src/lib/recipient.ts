import type { RecipientField } from "./types";

/** A recipient value ready for the screen: its label and what to show. */
export interface RecipientLine {
  key: string;
  label: string;
  /** What the reseller sent — the thing to copy. */
  value: string;
  /** What to read: an option's name for a select ("Asia"), else the value. */
  shown: string;
}

function pick(map: Record<string, string> | null, locale: string): string | undefined {
  if (map === null) return undefined;
  return map[locale] ?? map.ru ?? map.en;
}

/**
 * Label the order's recipient in the cabinet's locale.
 *
 * Labels come from the product's own form, so they read the way the order form
 * did; a label missing in this locale falls back to Russian, then to the key.
 * `undefined` is an API older than the field.
 */
export function recipientLines(
  fields: RecipientField[] | undefined,
  locale: string,
): RecipientLine[] {
  return (fields ?? []).map((field) => ({
    key: field.key,
    label: pick(field.label, locale) ?? field.key,
    value: field.value,
    shown: pick(field.value_label, locale) ?? field.value,
  }));
}

/**
 * Supplier bookkeeping in a delivery artifact: the receipt's own `status`
 * ("shipped") and its `kind`. The order's status is already on the page, so
 * these only read as noise beside a code or a login.
 */
const BOOKKEEPING = new Set(["status", "kind"]);

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/**
 * Flatten a delivery artifact into copyable lines.
 *
 * The shape follows `artifact_kind` and the vocabulary grows, so this reads
 * whatever is there rather than switching on the kind: `code`, `codes`, a
 * receipt's fields. Anything that is not a string or a list of strings is
 * rendered as JSON — visible and copyable, which beats hiding it.
 */
export function visibleArtifactLines(
  artifact: Record<string, unknown>,
): { key: string; value: string }[] {
  return Object.entries(artifact).flatMap(([key, value]) => {
    if (BOOKKEEPING.has(key)) return [];
    if (typeof value === "string") return [{ key, value }];
    if (isStringArray(value)) {
      return value.map((item, index) => ({ key: `${key}[${String(index)}]`, value: item }));
    }
    return [{ key, value: JSON.stringify(value) }];
  });
}
