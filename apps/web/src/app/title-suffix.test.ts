/**
 * A page title spells the site name only if the page opts out of the template.
 *
 * `layout.tsx` sets `title: { template: "%s — yupay" }`, so Next appends the
 * brand to every page title handed over as a plain string. A title that also
 * carries its own "| YuPay" therefore ships doubled — which is what the Steam
 * gifts pages did: `Steam Игры — дарите игры в Steam | YuPay — yupay` on the
 * hub, and the same tail on all ~4 400 game pages, since they share the
 * template. `/store/steam` next door was clean the whole time.
 *
 * The escape hatch is `title: { absolute }`, which bypasses the template; the
 * brand and how-to pages use it and so are allowed to spell the brand
 * themselves. That is the actual rule, and it is why this test is an allowlist
 * rather than a blanket ban: a title carrying the brand has to name the page
 * that opts out, or it is a bug.
 *
 * Pinned here rather than in a render test because the fault is a property of
 * the strings — each half looks correct in review, and the doubling only
 * appears after the framework applies the template, in every locale at once.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const LOCALES = ["ru", "en", "uz"] as const;

/** The suffix `layout.tsx` appends, in the spellings a copywriter might use. */
const BRAND = /\|\s*yupay\b|—\s*yupay\b/i;

/**
 * Titles allowed to spell the brand, each because its page passes
 * `title: { absolute }` and so never gets the template applied.
 *
 * Adding a row here is a claim you have to be able to point at in the page
 * source. Adding one to silence this test is how the doubling comes back.
 */
const ABSOLUTE_TITLES: Record<string, string> = {
  "store.brandMetaTitle": "[locale]/store/[brandSlug]/page.tsx — title: { absolute }",
  "store.howToMetaTitle": "[locale]/store/[brandSlug]/how-to/page.tsx — title: { absolute }",
};

/** Every `*Title`-ish leaf in a message catalog, as `path -> value`. */
function titleStrings(node: unknown, path: string[] = []): [string, string][] {
  if (typeof node === "string") {
    const key = path[path.length - 1] ?? "";
    return /title$/i.test(key) ? [[path.join("."), node]] : [];
  }
  if (node !== null && typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
      titleStrings(v, [...path, k]),
    );
  }
  return [];
}

function catalog(locale: string): unknown {
  const raw = readFileSync(
    resolve(process.cwd(), `../../packages/i18n/locales/${locale}/web.json`),
    "utf8",
  );
  return JSON.parse(raw) as unknown;
}

describe.each(LOCALES)("%s message catalog", (locale) => {
  it("spells the site name only in titles that opt out of the template", () => {
    const offenders = titleStrings(catalog(locale))
      .filter(([path, value]) => BRAND.test(value) && !(path in ABSOLUTE_TITLES))
      .map(([path, value]) => `${path}: ${value}`);

    expect(offenders, "layout.tsx already appends « — yupay »").toEqual([]);
  });

  it("keeps the allowlist honest", () => {
    // An entry that no longer spells the brand is stale: it claims an
    // exemption nothing needs, and the next person reads it as precedent.
    const brandy = new Set(
      titleStrings(catalog(locale))
        .filter(([, value]) => BRAND.test(value))
        .map(([path]) => path),
    );
    const stale = Object.keys(ABSOLUTE_TITLES).filter((path) => !brandy.has(path));

    expect(stale, "these no longer spell the brand — drop the exemption").toEqual([]);
  });
});
