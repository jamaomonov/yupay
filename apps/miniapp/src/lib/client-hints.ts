/**
 * Passive signals about the browser placing an order, kept as chargeback
 * evidence (ADR-0044).
 *
 * Deliberately only things the browser already tells every site it visits: no
 * canvas, font or audio probing. Those identify a device ACROSS sites, which is
 * a different activity with different consent obligations — and they would not
 * make a dispute pack stronger anyway. What helps there is corroboration: a
 * Tashkent IP next to an Asia/Tashkent clock and a ru-UZ locale reads very
 * differently from the same IP next to a mismatched pair.
 *
 * Every field is best-effort. A browser that refuses one must not stop a sale,
 * so failures resolve to an absent key rather than an exception.
 *
 * No `navigator.platform`: it is deprecated, and the User-Agent captured
 * server-side already carries the same fact — collecting it twice would add
 * data without adding evidence.
 */
export interface ClientHints {
  timezone?: string;
  locale?: string;
  screen?: string;
}

/** Values the server rejects outright — no point sending them. */
const MAX = { timezone: 64, locale: 32, screen: 32 } as const;

function trim(value: string | undefined, max: number): string | undefined {
  if (!value) return undefined;
  const clean = value.trim().slice(0, max);
  return clean || undefined;
}

function timezone(): string | undefined {
  try {
    return trim(Intl.DateTimeFormat().resolvedOptions().timeZone, MAX.timezone);
  } catch {
    // Intl is universally available, but a locked-down browser can throw here.
    return undefined;
  }
}

function screenSize(): string | undefined {
  const { width, height } = window.screen;
  if (!width || !height) return undefined;
  // devicePixelRatio rounded to one decimal: the raw value varies with zoom
  // level on the same device, which would read as a mismatch rather than a
  // match when the pack is compared against a later session.
  const dpr = Math.round(window.devicePixelRatio * 10) / 10;
  return `${String(width)}x${String(height)}@${String(dpr)}`;
}

export function collectClientHints(): ClientHints | undefined {
  // Server-rendered call sites have no `window`; returning undefined keeps the
  // key out of the request body entirely rather than sending an empty object.
  if (typeof window === "undefined") return undefined;

  // Keys are added only when the signal exists. Under
  // `exactOptionalPropertyTypes` an explicit `undefined` is not the same as an
  // omitted field, and the server draws the same distinction: an absent key
  // means "not reported", not "reported as empty".
  const candidates: [keyof ClientHints, string | undefined][] = [
    ["timezone", timezone()],
    ["locale", trim(navigator.language, MAX.locale)],
    ["screen", screenSize()],
  ];

  const hints: ClientHints = {};
  for (const [key, value] of candidates) {
    if (value !== undefined) hints[key] = value;
  }

  return Object.keys(hints).length > 0 ? hints : undefined;
}
