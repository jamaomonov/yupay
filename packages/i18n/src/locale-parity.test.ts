/**
 * Every locale carries the same keys.
 *
 * AGENTS.md §11 says CI fails when a locale is missing a key. It did not —
 * nothing checked, so a key added to `ru` alone would ship as a raw
 * `namespace.key` string in front of an English or Uzbek visitor, and a key
 * deleted from one locale only would linger as dead weight in the others.
 */

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const LOCALES_DIR = resolve(process.cwd(), "locales");
const REFERENCE = "ru";

/** Flatten nested message objects to dotted paths. */
function paths(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    paths(child, prefix ? `${prefix}.${key}` : key),
  );
}

function load(locale: string, file: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(LOCALES_DIR, locale, file), "utf8")) as Record<
    string,
    unknown
  >;
}

const locales = readdirSync(LOCALES_DIR).filter((name) => !name.startsWith("."));
const files = readdirSync(resolve(LOCALES_DIR, REFERENCE)).filter((f) => f.endsWith(".json"));

describe("locale parity", () => {
  it("ships all three locales", () => {
    expect(locales.sort()).toEqual(["en", "ru", "uz"]);
  });

  for (const file of files) {
    for (const locale of ["en", "uz"]) {
      it(`${locale}/${file} matches ${REFERENCE}/${file}`, () => {
        const reference = new Set(paths(load(REFERENCE, file)));
        const actual = new Set(paths(load(locale, file)));
        const missing = [...reference].filter((k) => !actual.has(k));
        const extra = [...actual].filter((k) => !reference.has(k));
        // Reported together: a rename shows up as one of each, and seeing both
        // halves at once is what makes it obvious.
        expect({ missing, extra }).toEqual({ missing: [], extra: [] });
      });
    }
  }
});
