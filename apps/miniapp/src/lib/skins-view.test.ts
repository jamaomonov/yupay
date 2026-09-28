import { describe, expect, it } from "vitest";

import type { SkinItem } from "@yupay/utils";

import { accumulateSkins } from "./skins-view";

const item = (slug: string) => ({ slug }) as SkinItem; // only the key matters here

describe("accumulateSkins", () => {
  it("appends the next page and drops duplicates", () => {
    const out = accumulateSkins([item("a"), item("b")], [item("b"), item("c")], true);
    expect(out.map((i) => i.slug)).toEqual(["a", "b", "c"]);
  });

  it("a first page replaces", () => {
    const out = accumulateSkins([item("a")], [item("z")], false);
    expect(out.map((i) => i.slug)).toEqual(["z"]);
  });
});
