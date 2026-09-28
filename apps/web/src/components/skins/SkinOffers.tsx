"use client";

import { createContext, useContext, useEffect, useState } from "react";

import type { SkinListing } from "@/lib/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

/** `null` while loading; `[]` when there are none or the read failed. */
const OffersContext = createContext<SkinListing[] | null>(null);

/**
 * Loads an item's live offers once, in the browser, for both readers: the
 * headline price (the cheapest offer is the price someone can pay) and the
 * offers list. A page render never waits on it — the listings read is the one
 * catalogue call that can reach the supplier.
 */
export function SkinOffersProvider({ slug, children }: { slug: string; children: ReactNode }) {
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  useEffect(() => {
    let live = true;
    setOffers(null);
    fetchSkinListings(slug)
      .then((r) => {
        if (live) setOffers(r.items);
      })
      .catch(() => {
        if (live) setOffers([]);
      });
    return () => {
      live = false;
    };
  }, [slug]);
  return <OffersContext.Provider value={offers}>{children}</OffersContext.Provider>;
}

export function useSkinOffers(): SkinListing[] | null {
  return useContext(OffersContext);
}
