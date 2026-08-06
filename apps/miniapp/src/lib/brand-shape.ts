/**
 * Which shape a brand's top-up screen takes, remembered between visits.
 *
 * A skeleton is a promise about the form that is coming. The top-up screen
 * always drew a 2×2 grid of package cards while it loaded — but a
 * variable-amount product (Steam) resolves into a single amount field instead,
 * so the placeholder promised the wrong interface and then jumped.
 *
 * The flag only becomes knowable once the SKUs arrive, which is exactly too
 * late. Caching it per brand fixes every visit after the first, and a wrong
 * entry corrects itself on the next load.
 */

const KEY = "yupay.brandShape";

type Shape = "packages" | "amount";

function readAll(): Record<string, Shape> {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, Shape>) : {};
  } catch {
    // Storage blocked or corrupt — the grid fallback is still correct for
    // every brand but one.
    return {};
  }
}

/** Last known shape for a brand, or `null` on a first visit. */
export function getBrandShape(slug: string | undefined): Shape | null {
  if (!slug) return null;
  return readAll()[slug] ?? null;
}

export function rememberBrandShape(slug: string | undefined, shape: Shape): void {
  if (!slug) return;
  try {
    const all = readAll();
    if (all[slug] === shape) return;
    all[slug] = shape;
    window.localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* not persisted; the screen still renders correctly this time */
  }
}
