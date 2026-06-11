/**
 * Runtime locale-parity guard (the docstring in messages.ts promises one).
 *
 * TypeScript's structural check catches missing keys at compile time, but a
 * key with the wrong *shape* (string vs plural object) or an extra key in
 * en/uz would slip through type widening — this asserts exact parity.
 */

import { describe, expect, it } from "vitest";

import { CATALOGS } from "./messages";

// Catalogs are flat: a value is either a string or a plural-form object.
type PluralForms = Record<string, string>;
type Tree = Record<string, string | PluralForms>;

function shapeOf(value: string | PluralForms): string {
  if (typeof value === "string") return "string";
  return `{${Object.keys(value).sort().join(",")}}`;
}

describe("message catalogs", () => {
  const ru = CATALOGS.ru as unknown as Tree;

  for (const locale of ["en", "uz"] as const) {
    it(`${locale} has exactly the same keys and value shapes as ru`, () => {
      const other = CATALOGS[locale] as unknown as Tree;

      expect(Object.keys(other).sort()).toEqual(Object.keys(ru).sort());
      for (const key of Object.keys(ru)) {
        expect(shapeOf(other[key]!), `key "${key}" in ${locale}`).toBe(shapeOf(ru[key]!));
      }
    });

    it(`${locale} has no empty translations`, () => {
      const other = CATALOGS[locale] as unknown as Tree;
      for (const [key, value] of Object.entries(other)) {
        if (typeof value === "string") {
          expect(value.trim(), `key "${key}" in ${locale}`).not.toBe("");
        } else {
          for (const [form, text] of Object.entries(value)) {
            expect(text.trim(), `key "${key}.${form}" in ${locale}`).not.toBe("");
          }
        }
      }
    });
  }
});
