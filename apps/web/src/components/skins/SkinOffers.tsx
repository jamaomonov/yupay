"use client";

import { repriceOffer } from "@yupay/utils";
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
  /** The server quoted another price for this offer: show and charge that one. */
  reprice: (listingId: number, expectedUsd: string) => void;
  /** This offer was sold: take it off the page. */
  drop: (listingId: number) => void;
}

const OffersContext = createContext<OffersState>({
  offers: null,
  selected: null,
  select: () => undefined,
  reprice: () => undefined,
  drop: () => undefined,
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
  const reprice = (listingId: number, expectedUsd: string) => {
    setOffers(
      (all) =>
        all?.map((o) => (o.listing_id === listingId ? repriceOffer(o, expectedUsd) : o)) ?? null,
    );
  };
  const drop = (listingId: number) => {
    setOffers((all) => all?.filter((o) => o.listing_id !== listingId) ?? null);
  };
  return (
    <OffersContext.Provider value={{ offers, selected, select: setSelectedId, reprice, drop }}>
      {children}
    </OffersContext.Provider>
  );
}

export function useSkinOffers(): SkinListing[] | null {
  return useContext(OffersContext).offers;
}

/** The offer to buy and how to change it (a row's «Купить», a "next offer", a new price). */
export function useSelectedOffer(): Omit<OffersState, "offers"> {
  const { selected, select, reprice, drop } = useContext(OffersContext);
  return { selected, select, reprice, drop };
}
