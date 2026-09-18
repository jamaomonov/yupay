import { describe, expect, it } from "vitest";

import { capabilitiesFor, DENOM_CACHE_SUPPLIERS } from "./types";

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

/**
 * The two defaults for an unknown supplier are asymmetric on purpose, and the
 * asymmetry is decided by what a wrong guess costs rather than by tidiness.
 */
describe("capabilitiesFor on an unknown supplier", () => {
  it("offers catalogue sync, because a wrong guess there answers 422 and says so", () => {
    expect(capabilitiesFor("some-future-supplier").catalogueSync).toBe(true);
  });

  it("does not offer the game importer, which would succeed at the wrong thing", () => {
    // The import link posts to `/g2b/import`, hardcoded. For any other
    // supplier it would not fail — it would import a G2B game while the
    // operator is looking at someone else's catalogue. A silent wrong action
    // is worse than a missing button.
    expect(capabilitiesFor("some-future-supplier").gameImport).toBe(false);
  });

  it("still gives a known supplier its own narrower truth", () => {
    expect(capabilitiesFor("nova")).toEqual({ catalogueSync: true, gameImport: false });
    expect(capabilitiesFor("g2b")).toEqual({ catalogueSync: true, gameImport: true });
  });
});
