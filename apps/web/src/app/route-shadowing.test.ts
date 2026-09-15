/**
 * A brand with its own directory must carry every page `[brandSlug]` provides.
 *
 * Next resolves a static path segment ahead of a dynamic one, left to right.
 * `app/[locale]/store/steam-gifts/` therefore wins over
 * `app/[locale]/store/[brandSlug]/` for every URL beneath it — including the
 * ones only `[brandSlug]` implements. `/store/steam-gifts/how-to` fell into
 * `steam-gifts/[appId]` instead, `Number("how-to")` came back NaN, and the page
 * 404'd.
 *
 * It hid for a long time: the prerendered HTML outlived the collision and
 * answered 200 until something made that path revalidate, while `sitemap.ts`
 * emitted `/store/<slug>/how-to` for every brand — so a crawler was being
 * handed a URL that had quietly become a 404, and nothing on the site said so.
 *
 * The check is structural rather than behavioural because that is where the
 * fault lives: a directory appears, and pages that used to exist stop existing,
 * somewhere else, with no error at build time.
 */

import { existsSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const STORE = resolve(process.cwd(), "src/app/[locale]/store");

/** Directories under `store/` that are literal path segments, not params. */
function staticBrandDirs(): string[] {
  return readdirSync(STORE, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith("["))
    .map((e) => e.name);
}

/** Sub-pages `[brandSlug]` serves, which a static sibling therefore shadows. */
function brandSubPages(): string[] {
  return readdirSync(resolve(STORE, "[brandSlug]"), { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith("["))
    .filter((e) => existsSync(resolve(STORE, "[brandSlug]", e.name, "page.tsx")))
    .map((e) => e.name);
}

describe("a static brand directory", () => {
  const dirs = staticBrandDirs();

  it("is a shape this test can still reason about", () => {
    // If `[brandSlug]` ever stops existing, or gains no sub-pages, the loop
    // below passes by having nothing to check — which is the failure mode of
    // every structural test. Assert the premises hold.
    expect(existsSync(resolve(STORE, "[brandSlug]", "page.tsx"))).toBe(true);
    expect(brandSubPages().length).toBeGreaterThan(0);
    expect(dirs.length).toBeGreaterThan(0);
  });

  it.each(dirs)("%s implements every page [brandSlug] has", (dir) => {
    const missing = brandSubPages().filter(
      (sub) => !existsSync(resolve(STORE, dir, sub, "page.tsx")),
    );

    expect(
      missing,
      `/store/${dir}/<page> resolves into ${dir}/, not [brandSlug]/ — ` +
        "these are 404s that sitemap.ts still advertises",
    ).toEqual([]);
  });
});
