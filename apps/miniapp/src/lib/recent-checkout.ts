/**
 * Persisted recall of the last successful checkout per brand.
 *
 * Stores ``fulfillment_data`` (e.g. ``{ player_id: "123456" }``) keyed by
 * brand slug in localStorage so a returning customer doesn't retype their
 * PUBG ID every visit. Server-state of choice is the API; this is a UX
 * shortcut, not a source of truth.
 *
 * The store is intentionally tiny:
 *   - 1 entry per brand
 *   - capped at 32 brands total (LRU eviction by updated_at)
 *   - cleared by ``useLogout`` so a shared device doesn't leak the last
 *     player_id to the next Telegram user.
 */

const STORAGE_KEY = "yupay.miniapp.recent_fulfillment_v1";
const MAX_BRANDS = 32;

export interface RecentFulfillment {
  brand_slug: string;
  fulfillment_data: Record<string, string>;
  updated_at: number; // ms epoch
}

type Store = Record<string, RecentFulfillment>;

function readStore(): Store {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!isStore(parsed)) return {};
    return parsed;
  } catch {
    return {};
  }
}

function writeStore(store: Store): void {
  try {
    // Cap the size — keep MAX_BRANDS most recent by updated_at.
    const entries = Object.values(store);
    if (entries.length > MAX_BRANDS) {
      entries.sort((a, b) => b.updated_at - a.updated_at);
      const kept = entries.slice(0, MAX_BRANDS);
      const next: Store = {};
      for (const e of kept) next[e.brand_slug] = e;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // localStorage may be unavailable in some Telegram clients; non-fatal.
  }
}

function isStore(v: unknown): v is Store {
  if (typeof v !== "object" || v === null) return false;
  return Object.values(v).every(
    (entry) =>
      typeof entry === "object" &&
      entry !== null &&
      "brand_slug" in entry &&
      "fulfillment_data" in entry &&
      "updated_at" in entry,
  );
}

export function getRecentFulfillment(
  brandSlug: string | null | undefined,
): RecentFulfillment | null {
  if (!brandSlug) return null;
  const store = readStore();
  return store[brandSlug] ?? null;
}

export function rememberFulfillment(brandSlug: string, data: Record<string, unknown>): void {
  if (!brandSlug || Object.keys(data).length === 0) return;
  // Sanitise: only persist string scalars. Other shapes are surely not
  // meaningful "remember this" values (and shouldn't bloat localStorage).
  const cleaned: Record<string, string> = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === "string" && v.trim().length > 0) cleaned[k] = v.trim();
  }
  if (Object.keys(cleaned).length === 0) return;
  const store = readStore();
  store[brandSlug] = {
    brand_slug: brandSlug,
    fulfillment_data: cleaned,
    updated_at: Date.now(),
  };
  writeStore(store);
}

export function forgetFulfillment(brandSlug: string): void {
  const store = readStore();
  if (!(brandSlug in store)) return;
  delete store[brandSlug];
  writeStore(store);
}

export function clearAllRecent(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignored
  }
}
