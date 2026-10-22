/**
 * The saved player form, read back safely. Plain TS, unit-tested; storage is `player-memory.ts`.
 */

/** Strings only, trimmed, empties dropped: what is safe to put back into the form. */
export function parseSaved(raw: string | null): Record<string, string> {
  if (raw === null) return {};
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
    const out: Record<string, string> = {};
    for (const [field, text] of Object.entries(value)) {
      if (typeof text === "string" && text.trim() !== "") out[field] = text.trim();
    }
    return out;
  } catch {
    return {};
  }
}
