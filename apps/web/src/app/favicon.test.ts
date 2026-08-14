import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Yandex Webmaster reported "файл favicon не найден" for weeks while Google was
 * happily showing the mark. Everything HTTP-level checked out — 200, correct
 * `image/x-icon`, no redirect, not robots-blocked — so the remaining suspects
 * were the file's own shape, and Yandex documents exactly what it accepts:
 * 120x120, 32x32 or 16x16, in SVG (recommended) / ICO / GIF / JPEG / PNG / BMP.
 *
 * The old file carried a 48x48 (not on that list, and the size Next.js then
 * advertised in `<link sizes>`) and stored every image PNG-compressed — legal
 * per the Vista+ ICO spec, but only BMP-encoded entries are universally
 * readable. Both are invisible in a browser, which is why this is pinned here.
 */

const ICO = join(__dirname, "favicon.ico");
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Yandex's supported favicon dimensions. */
const ALLOWED = new Set([120, 32, 16]);

interface IconEntry {
  size: number;
  bpp: number;
  png: boolean;
}

function parseIco(buf: Buffer): IconEntry[] {
  expect(buf.readUInt16LE(0)).toBe(0); // reserved
  expect(buf.readUInt16LE(2)).toBe(1); // type: icon
  const count = buf.readUInt16LE(4);
  return Array.from({ length: count }, (_, i) => {
    const dir = 6 + i * 16;
    const offset = buf.readUInt32LE(dir + 12);
    return {
      size: buf.readUInt8(dir) || 256,
      bpp: buf.readUInt16LE(dir + 6),
      png: buf.subarray(offset, offset + 8).equals(PNG_MAGIC),
    };
  });
}

describe("favicon.ico", () => {
  const entries = parseIco(readFileSync(ICO));

  it("only ships sizes Yandex accepts", () => {
    expect(entries.length).toBeGreaterThan(0);
    for (const e of entries) expect(ALLOWED.has(e.size)).toBe(true);
  });

  it("stores every image BMP-encoded, never PNG-compressed", () => {
    for (const e of entries) expect(e.png).toBe(false);
  });

  it("keeps 32-bit colour so the mark stays transparent", () => {
    for (const e of entries) expect(e.bpp).toBe(32);
  });
});

describe("favicon.svg", () => {
  // Yandex wants the file in the root *named* favicon; Next serves the
  // app-router icon as `/icon.svg?<hash>`, which is neither. This copy in
  // public/ is the URL their robot looks for.
  it("is served from the site root under the name Yandex looks for", () => {
    const svg = readFileSync(join(__dirname, "..", "..", "public", "favicon.svg"), "utf8");
    expect(svg).toContain("<svg");
    // Square canvas — a non-square mark is why Google once fell back to a globe.
    expect(svg).toMatch(/width="(\d+)"\s+height="\1"/);
  });
});
