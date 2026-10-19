import type { Brand } from "../types";

import { matchesText } from "@/lib/textSearch";

/** One tri-state filter: no constraint, the flag on, the flag off. */
export type FlagFilter = "" | "yes" | "no";

export interface BrandFilters {
  active: FlagFilter;
  retail: FlagFilter;
  b2b: FlagFilter;
  /** Text search over the brand's names in every locale and its slug. */
  query?: string;
}

function matches(filter: FlagFilter, value: boolean): boolean {
  if (filter === "") return true;
  return filter === "yes" ? value : !value;
}

/** The brands every set filter agrees on. Order is kept. */
export function filterBrands(brands: readonly Brand[], f: BrandFilters): Brand[] {
  return brands.filter(
    (b) =>
      matches(f.active, b.active) &&
      matches(f.retail, b.visible_retail) &&
      matches(f.b2b, b.visible_b2b) &&
      matchesText(f.query ?? "", [b.slug, ...b.translations.map((t) => t.name)]),
  );
}

/** Reads a URL value; anything unknown means "no filter". */
export function parseFlagFilter(raw: string): FlagFilter {
  return raw === "yes" || raw === "no" ? raw : "";
}
