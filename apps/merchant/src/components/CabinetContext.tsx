"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import type { Catalog, Profile } from "@/lib/types";

import { api } from "@/lib/api";

interface CabinetData {
  profile: Profile | null;
  catalog: Catalog | null;
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
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [search, setSearch] = useState("");
  const [searchPlaceholder, setSearchPlaceholder] = useState<string | null>(null);
  const pathname = usePathname();
  const previousPath = useRef(pathname);

  // A query typed on Orders must not silently filter the catalog after a
  // navigation — the box is cleared, and the new screen declares its own
  // placeholder or none.
  //
  // On a **change** only, never on mount: child effects run before parent
  // ones, so a clear here would wipe the placeholder the screen below had
  // just set and the box would never appear on a cold load.
  useEffect(() => {
    if (previousPath.current === pathname) return;
    previousPath.current = pathname;
    setSearch("");
    setSearchPlaceholder(null);
  }, [pathname]);

  const refreshProfile = useCallback(() => {
    void api<Profile>("/me").then(setProfile, () => undefined);
  }, []);

  useEffect(() => {
    refreshProfile();
    void api<Catalog>("/catalog").then(setCatalog, () => {
      // An empty catalog, not a null one: the difference is "we asked and
      // there is nothing" versus "we have not asked yet", and the screens
      // render an empty state for the first and a blank for the second.
      setCatalog({ brands: [] });
    });
  }, [refreshProfile]);

  return (
    <Ctx.Provider
      value={{
        profile,
        catalog,
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
  }, [placeholder, setSearchPlaceholder]);
  return search;
}

export interface Section {
  slug: string;
  name: string;
  count: number;
}

/**
 * The catalog's sections, in the order the price list returns them.
 *
 * A brand whose category row is missing lands under `null` in the API and is
 * skipped here rather than given a section of its own: the sidebar is
 * navigation, and a section called "—" navigates nowhere useful. The brand
 * itself still appears under «Все».
 */
export function sectionsOf(catalog: Catalog | null): Section[] {
  const seen = new Map<string, Section>();
  for (const brand of catalog?.brands ?? []) {
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
  return [...seen.values()];
}
