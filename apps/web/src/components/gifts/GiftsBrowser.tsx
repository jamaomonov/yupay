"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { GiftCard } from "./GiftCard";

import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/lib/button";
import { searchGifts, type GiftsList } from "@/lib/gifts";

/** How still the query has to be before it's sent — mirrors `PromoField.tsx`'s
 *  `REPRICE_DEBOUNCE_MS`: firing one request per keystroke would spend the
 *  catalog endpoint's rate budget on a single visit. */
const SEARCH_DEBOUNCE_MS = 400;

/** Placeholder count for the loading grid — purely visual, doesn't need to
 *  match the server's page size. */
const SKELETON_COUNT = 8;

export function GiftsBrowser({ locale, initial }: { locale: string; initial: GiftsList }) {
  const t = useTranslations("web.gifts");
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);

  // Debounce, mirroring `PromoField.tsx`'s `setTimeout` + cleanup pattern.
  // Typing resets pagination back to the first page of the new query.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(raw.trim());
      setOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw]);

  const hasQuery = query.length > 0;

  const result = useQuery({
    queryKey: ["gifts", locale, query, offset],
    queryFn: () => searchGifts(locale, query, offset),
    // An empty query costs nothing: the server-fetched `initial` page below
    // covers it, so a visitor who never searches never fires a client fetch.
    enabled: hasQuery,
    // "Показать ещё" mounts a new key (a new offset), so without this the
    // grid unmounts to a skeleton and re-expands on every page — same
    // reasoning as the wallet page's own "Показать ещё".
    placeholderData: keepPreviousData,
  });

  const list: GiftsList = hasQuery ? (result.data ?? { items: [], total: 0 }) : initial;
  const showSkeletons = hasQuery && result.isPending;
  const showError = hasQuery && result.isError;
  const canShowMore = list.items.length > 0 && offset + list.items.length < list.total;

  return (
    <div className="mt-10">
      <div className="relative max-w-[420px]">
        <Search
          size={16}
          className="text-tx-dim pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
        />
        <input
          type="search"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
          }}
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          className="border-border bg-card rounded-btn h-11 w-full border pl-9 pr-3 text-sm"
        />
      </div>

      {showError ? (
        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <p className="text-tx-mute text-[14px]">{t("search.error")}</p>
          <button
            type="button"
            onClick={() => void result.refetch()}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            {t("search.retry")}
          </button>
        </div>
      ) : showSkeletons ? (
        <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: SKELETON_COUNT }, (_, i) => (
            <Skeleton key={i} className="aspect-[3/4] rounded-xl" />
          ))}
        </div>
      ) : list.items.length === 0 ? (
        <p className="text-tx-mute mt-10 text-center text-[14px]">{t("search.empty")}</p>
      ) : (
        <>
          <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {list.items.map((app) => (
              <GiftCard key={app.app_id} app={app} locale={locale} />
            ))}
          </div>
          {canShowMore && (
            <div className="mt-8 flex justify-center">
              <button
                type="button"
                onClick={() => {
                  setOffset((o) => o + list.items.length);
                }}
                disabled={result.isFetching}
                className={buttonStyles({ variant: "ghost", size: "sm" })}
              >
                {t("search.showMore")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
