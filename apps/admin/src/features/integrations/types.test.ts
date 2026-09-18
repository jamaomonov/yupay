import { describe, expect, it } from "vitest";

import { DENOM_CACHE_SUPPLIERS } from "./types";

/**
 * `MappingEditPage` used to branch on `supplier === "g2b"` to choose between
 * G2B's live `DenomPicker` and the cache-backed `DenomCatalogPicker` — an
 * exclusion, when the backend's own rule
 * (`DENOM_SYNCABLE_SUPPLIERS` in `catalog_sync.py`) is a positive allowlist.
 * A fourth mappable supplier that isn't denomination-syncable would have
 * silently gotten `DenomCatalogPicker` plus a pull button that 422s — the
 * exact failure `DenomCatalogPicker`'s own docstring warns about.
 *
 * `DENOM_CACHE_SUPPLIERS` mirrors the backend set so the wizard branches on
 * membership instead — change one, change both (ADR-0082).
 */
describe("DENOM_CACHE_SUPPLIERS", () => {
  it("mirrors the backend's DENOM_SYNCABLE_SUPPLIERS allowlist — nova and gengine only", () => {
    expect(DENOM_CACHE_SUPPLIERS.has("nova")).toBe(true);
    expect(DENOM_CACHE_SUPPLIERS.has("gengine")).toBe(true);
  });

  it("excludes G2B, which keeps its own live DenomPicker instead", () => {
    expect(DENOM_CACHE_SUPPLIERS.has("g2b")).toBe(false);
  });

  it("excludes an unlisted supplier — a future mappable supplier must be added here explicitly", () => {
    expect(DENOM_CACHE_SUPPLIERS.has("some-future-supplier")).toBe(false);
  });
});
