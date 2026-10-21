"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import type { CatalogSummary, P2PStatus, Profile } from "@/lib/types";

import { api } from "@/lib/api";

interface CabinetData {
  profile: Profile | null;
  /**
   * One card per brand — not the price list. The full tree is 2.3 MB after the
   * 2026-10 import, and every cabinet screen (orders, settings…) was downloading
   * it for the sidebar's section list; the brand page fetches its own subtree.
   */
  catalog: CatalogSummary | null;
  /** Whether self-serve top-up is on for this reseller; `null` until asked. */
  p2p: P2PStatus | null;
  /** Re-read the profile — the balance moves when an order is placed. */
  refreshProfile: () => void;
  /**
   * The search box in the top bar.
   *
   * The **shell** owns the text and the screen reads it, rather than each
   * screen owning a box of its own. That is what lets one bar sit above every
   * screen without each of them having to remember to render it — miss one
   * and the balance disappears from that page.
   */
  search: string;
  setSearch: (value: string) => void;
  /** What the box should say it searches, or `null` to hide it entirely. */
  searchPlaceholder: string | null;
  setSearchPlaceholder: (value: string | null) => void;
}

const Ctx = createContext<CabinetData>({
  profile: null,
  catalog: null,
  p2p: null,
  refreshProfile: () => undefined,
  search: "",
  setSearch: () => undefined,
  searchPlaceholder: null,
  setSearchPlaceholder: () => undefined,
});

/**
 * The two things the whole cabinet reads, fetched once by the shell.
 *
 * The profile carries the balance, which the top bar shows on every screen;
 * the catalog carries the sections, which the sidebar lists on every screen.
 * Before this each page fetched its own, so the catalog page and a brand page
 * pulled the same price list twice in a row and the balance was only on the
 * dashboard.
 *
 * A shared catalog costs the four non-catalog screens one fetch they did not
 * make before. That is the trade for a sidebar whose sections are **the ones
 * that actually have something in them** — derived from the same tree the
 * catalog renders, rather than from a second query that would have to repeat
 * the margin-floor rule and could disagree with it.
 */
export function CabinetProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [catalog, setCatalog] = useState<CatalogSummary | null>(null);
  const [p2p, setP2p] = useState<P2PStatus | null>(null);
  const [search, setSearch] = useState("");
  const [searchPlaceholder, setSearchPlaceholder] = useState<string | null>(null);
  const pathname = usePathname();
  const previousPath = useRef(pathname);

  // A query typed on Orders must not silently filter the catalog after a
  // navigation, so the text is cleared on a path change. The placeholder is
  // NOT touched here: child effects run before parent ones, so clearing it
  // here wiped the one the new screen had just declared — the box vanished on
  // the way back to the catalogue. Each screen removes its own on unmount
  // (`useSearch`), which React runs before the next screen's effects.
  useEffect(() => {
    if (previousPath.current === pathname) return;
    previousPath.current = pathname;
    setSearch("");
  }, [pathname]);

  const refreshProfile = useCallback(() => {
    void api<Profile>("/me").then(setProfile, () => undefined);
  }, []);

  useEffect(() => {
    refreshProfile();
    void api<CatalogSummary>("/catalog/summary").then(setCatalog, () => {
      // An empty catalog, not a null one: the difference is "we asked and
      // there is nothing" versus "we have not asked yet", and the screens
      // render an empty state for the first and a blank for the second.
      setCatalog({ brands: [] });
    });
    // A failed read means "not offered": the support link stays.
    void api<P2PStatus>("/p2p/status").then(setP2p, () => {
      setP2p({ enabled: false, fx_rate: null });
    });
  }, [refreshProfile]);

  return (
    <Ctx.Provider
      value={{
        profile,
        catalog,
        p2p,
        refreshProfile,
        search,
        setSearch,
        searchPlaceholder,
        setSearchPlaceholder,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useCabinet(): CabinetData {
  return useContext(Ctx);
}

/**
 * Put this screen's search in the top bar, and read what was typed.
 *
 * The placeholder is set on mount and cleared by the shell on navigation, so
 * a screen that stops calling this loses the box rather than inheriting the
 * previous one's.
 */
export function useSearch(placeholder: string): string {
  const { search, setSearchPlaceholder } = useCabinet();
  useEffect(() => {
    setSearchPlaceholder(placeholder);
    // Leaving the screen takes its box with it; a screen without search
    // declares nothing and the slot stays collapsed.
    return () => {
      setSearchPlaceholder(null);
    };
  }, [placeholder, setSearchPlaceholder]);
  return search;
}

export interface Section {
  slug: string;
  name: string;
  count: number;
}

/** A section the cabinet lifts out of the storefront's categories. */
export type PinnedSection = "steam" | "telegram";

/**
 * Brands that get a section of their own in the cabinet, whatever their
 * storefront category says (owner, 2026-10-21). Resellers come for exactly
 * these, and inside «Пополнения» they sat among three hundred game brands.
 * The storefront's categories are left alone — this is cabinet navigation.
 */
const PINNED: readonly { slug: PinnedSection; brands: readonly string[] }[] = [
  { slug: "steam", brands: ["steam"] },
  { slug: "telegram", brands: ["telegram-stars", "telegram-premium"] },
];

/** The pinned section a brand belongs to, if any. */
export function pinnedSectionOf(brandSlug: string): PinnedSection | null {
  return PINNED.find((entry) => entry.brands.includes(brandSlug))?.slug ?? null;
}

/** The section a brand is listed under: its pinned one, else its category. */
export function sectionSlugOf(brand: {
  slug: string;
  category_slug: string | null;
}): string | null {
  return pinnedSectionOf(brand.slug) ?? brand.category_slug;
}

/**
 * The catalog's sections: the pinned ones first, then the categories in the
 * order the price list returns them.
 *
 * A pinned section appears only when one of its brands is in the catalog, so
 * a brand hidden from resellers leaves no empty link behind. A brand whose
 * category row is missing lands under `null` in the API and is skipped here
 * rather than given a section of its own: the sidebar is navigation, and a
 * section called "—" navigates nowhere useful. The brand itself still appears
 * under «Все».
 */
export function sectionsOf(
  catalog: CatalogSummary | null,
  pinnedName: (slug: PinnedSection) => string = (slug) => slug,
): Section[] {
  const brands = catalog?.brands ?? [];
  const pinned: Section[] = [];
  for (const entry of PINNED) {
    const count = brands.filter((brand) => entry.brands.includes(brand.slug)).length;
    if (count > 0) pinned.push({ slug: entry.slug, name: pinnedName(entry.slug), count });
  }
  const seen = new Map<string, Section>();
  for (const brand of brands) {
    if (pinnedSectionOf(brand.slug) !== null) continue;
    if (brand.category_slug === null || brand.category_name === null) continue;
    const found = seen.get(brand.category_slug);
    if (found) found.count += 1;
    else
      seen.set(brand.category_slug, {
        slug: brand.category_slug,
        name: brand.category_name,
        count: 1,
      });
  }
  return [...pinned, ...seen.values()];
}
