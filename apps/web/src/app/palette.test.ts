/**
 * The palette must stay legible.
 *
 * `--tx-dim` shipped at 50% lightness and cleared WCAG AA on none of the four
 * surfaces it lands on — 4.26:1 down to 3.78:1 against a 4.5 floor — while
 * painting the checkout field labels, the footer headings and the breadcrumbs.
 * A colour tweak looks harmless in review, so the arithmetic lives here.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Resolved from the package root: the jsdom environment hands tests no file: URL.
const CSS = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

/** Read an HSL custom property (`--x: 226 17% 55%`) as an [h, s, l] triple. */
function hsl(name: string): [number, number, number] {
  const m = new RegExp(`--${name}:\\s*([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%`).exec(CSS);
  if (!m) throw new Error(`--${name} not found in globals.css`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function hslToRgb([h, s, l]: [number, number, number]): [number, number, number] {
  const sat = s / 100;
  const lig = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(lig, 1 - lig);
  const f = (n: number) => lig - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

function luminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(hslToRgb(hsl(a))), luminance(hslToRgb(hsl(b)))].sort(
    (x, y) => y - x,
  ) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** WCAG AA for body text. Every text token below carries body text somewhere. */
const AA = 4.5;

/** Every surface a text token can land on. `--muted` is the lightest, so worst. */
const SURFACES = ["bg", "card", "card-2", "muted"];

describe("palette contrast", () => {
  for (const text of ["foreground", "tx-mute", "tx-dim"]) {
    it(`--${text} clears AA on every surface`, () => {
      for (const surface of SURFACES) {
        expect(
          contrast(text, surface),
          `--${text} on --${surface} is ${contrast(text, surface).toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(AA);
      }
    });
  }

  it("keeps the muted levels ordered", () => {
    // Passing AA is not enough: if the two muted levels collapse into one, the
    // hierarchy the tokens exist to express is gone.
    expect(contrast("foreground", "muted")).toBeGreaterThan(contrast("tx-mute", "muted"));
    expect(contrast("tx-mute", "muted")).toBeGreaterThan(contrast("tx-dim", "muted"));
  });
});
