/**
 * The palette must stay legible.
 *
 * Both muted text levels once failed WCAG AA — light `--text-secondary` at
 * 4.20:1 and `--text-tertiary` at 2.26:1, the latter being what made the
 * sidebar's section captions almost invisible. Nothing caught it, because a
 * colour tweak looks harmless in review. This test reads the real token file
 * and does the arithmetic.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Resolved from the package root rather than import.meta.url: the jsdom
// environment does not hand tests a file: URL.
const CSS = readFileSync(resolve(process.cwd(), "src/styles/tokens-dim-slate.css"), "utf8");

// The light palette lives in a `:root, [data-theme="light"]` block; matching
// on the attribute selector avoids catching the earlier font-only `:root {}`.
const LIGHT = '\\[data-theme="light"\\]';
const DARK = '\\[data-theme="dark"\\]';

/** Read one custom property out of a given selector block. */
function token(selector: string, name: string): string {
  const block = new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(CSS);
  if (!block?.[1]) throw new Error(`no ${selector} block in tokens-dim-slate.css`);
  const value = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block[1]);
  if (!value?.[1]) throw new Error(`no --${name} in ${selector}`);
  return value[1];
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * (linear[0] ?? 0) + 0.7152 * (linear[1] ?? 0) + 0.0722 * (linear[2] ?? 0);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** WCAG AA for body text. Every level below carries body text somewhere. */
const AA = 4.5;

describe("palette contrast", () => {
  it.each(["text-primary", "text-secondary", "text-tertiary"])(
    "light --%s clears AA on the darkest light surface",
    (name) => {
      // --bg-base is darker than a card, so it is the worst case for dark text.
      const worstSurface = token(LIGHT, "bg-base");
      expect(contrast(token(LIGHT, name), worstSurface)).toBeGreaterThanOrEqual(AA);
    },
  );

  it.each(["text-primary", "text-secondary", "text-tertiary"])(
    "dark --%s clears AA on the lightest dark surface",
    (name) => {
      // Mirror image: a raised card is where dark-theme contrast is worst.
      const worstSurface = token(DARK, "bg-surface-2");
      expect(contrast(token(DARK, name), worstSurface)).toBeGreaterThanOrEqual(AA);
    },
  );

  it("keeps the three levels visually ordered", () => {
    // Passing AA is not enough: if secondary and tertiary collapse to the same
    // contrast, the hierarchy the tokens exist to express is gone.
    const base = token(LIGHT, "bg-base");
    const primary = contrast(token(LIGHT, "text-primary"), base);
    const secondary = contrast(token(LIGHT, "text-secondary"), base);
    const tertiary = contrast(token(LIGHT, "text-tertiary"), base);
    expect(primary).toBeGreaterThan(secondary);
    expect(secondary).toBeGreaterThan(tertiary);
  });
});
