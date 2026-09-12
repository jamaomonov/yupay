"use client";

import { createContext, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from "react";

interface Value {
  blogSlugs: Record<string, string> | null;
  setBlogSlugs: (next: Record<string, string> | null) => void;
}

const LocaleAlternatesContext = createContext<Value | null>(null);

export function LocaleAlternatesProvider({ children }: { children: ReactNode }) {
  const [blogSlugs, setBlogSlugs] = useState<Record<string, string> | null>(null);
  const value = useMemo(() => ({ blogSlugs, setBlogSlugs }), [blogSlugs]);
  return (
    <LocaleAlternatesContext.Provider value={value}>{children}</LocaleAlternatesContext.Provider>
  );
}

export function useBlogLocaleSlugs(): Record<string, string> | null {
  return useContext(LocaleAlternatesContext)?.blogSlugs ?? null;
}

/** Publish this article's locale_slugs to the header switcher for one mount. */
export function BlogLocaleBridge({ slugs }: { slugs: Record<string, string> }) {
  const setBlogSlugs = useContext(LocaleAlternatesContext)?.setBlogSlugs;
  const key = [...Object.entries(slugs)]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([loc, slug]) => `${loc}:${slug}`)
    .join("|");
  useLayoutEffect(() => {
    if (!setBlogSlugs) return;
    setBlogSlugs(slugs);
    return () => {
      setBlogSlugs(null);
    };
  }, [key, setBlogSlugs, slugs]);
  return null;
}
