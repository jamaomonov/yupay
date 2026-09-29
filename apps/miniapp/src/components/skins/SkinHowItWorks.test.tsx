import { describe, expect, it } from "vitest";

import { HOW_STEPS } from "./SkinHowItWorks";

import { lookup } from "@/lib/i18n/core";

/** No render harness here (see `PromoField.test.tsx`): every step must read in every locale. */
describe("SkinHowItWorks", () => {
  it.each(["ru", "en", "uz"] as const)("has every step in %s", (locale) => {
    for (const step of HOW_STEPS) {
      for (const part of ["title", "body"] as const) {
        const key = `cs2.how.${step}.${part}` as const;
        expect(lookup(locale, key)).not.toBe(key);
      }
    }
    expect(lookup(locale, "cs2.how.title")).not.toBe("cs2.how.title");
  });
});
