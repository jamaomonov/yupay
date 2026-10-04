import type { Brand } from "../types";

/** One tri-state filter: no constraint, the flag on, the flag off. */
export type FlagFilter = "" | "yes" | "no";

export interface BrandFilters {
  active: FlagFilter;
  retail: FlagFilter;
  b2b: FlagFilter;
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
      matches(f.b2b, b.visible_b2b),
  );
}

/** Reads a URL value; anything unknown means "no filter". */
export function parseFlagFilter(raw: string): FlagFilter {
  return raw === "yes" || raw === "no" ? raw : "";
}
