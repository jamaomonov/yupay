"use client";

import { createContext, useContext, useEffect, useState } from "react";

import type { SkinListing } from "@/lib/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

interface OffersState {
  /** `null` while loading; `[]` when there are none or the read failed. */
  offers: SkinListing[] | null;
  /** The offer the buy panel will buy — the cheapest until the customer picks one. */
  selected: SkinListing | null;
  select: (listingId: number) => void;
}

const OffersContext = createContext<OffersState>({
  offers: null,
  selected: null,
  select: () => undefined,
});

/**
 * Loads an item's live offers once, in the browser, for both readers: the
 * headline price (the cheapest offer is the price someone can pay) and the
 * offers list. A page render never waits on it — the listings read is the one
 * catalogue call that can reach the supplier.
 */
export function SkinOffersProvider({ slug, children }: { slug: string; children: ReactNode }) {
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
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
  const cheapest =
    offers && offers.length > 0
      ? offers.reduce((a, b) => (Number(b.price_usd) < Number(a.price_usd) ? b : a))
      : null;
  const selected = offers?.find((o) => o.listing_id === selectedId) ?? cheapest;
  return (
    <OffersContext.Provider value={{ offers, selected, select: setSelectedId }}>
      {children}
    </OffersContext.Provider>
  );
}

export function useSkinOffers(): SkinListing[] | null {
  return useContext(OffersContext).offers;
}

/** The offer to buy and how to change it (a row's «Купить», a "next offer"). */
export function useSelectedOffer(): Pick<OffersState, "selected" | "select"> {
  const { selected, select } = useContext(OffersContext);
  return { selected, select };
}
