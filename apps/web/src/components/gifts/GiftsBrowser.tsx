"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { GiftCard } from "./GiftCard";

import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/lib/button";
import { searchGifts, type GiftApp, type GiftsList } from "@/lib/gifts";

/** How still the query has to be before it's sent — mirrors `PromoField.tsx`'s
 *  `REPRICE_DEBOUNCE_MS`: firing one request per keystroke would spend the
 *  catalog endpoint's rate budget on a single visit. */
const SEARCH_DEBOUNCE_MS = 400;

/** Placeholder count for the loading grid — purely visual, doesn't need to
 *  match the server's page size. */
const SKELETON_COUNT = 8;

/**
 * `loading`/`error` are the *first* page of the current query (nothing to
 * show yet); `loadingMore`/`errorMore` are a "Показать ещё" page landing on
 * top of items already on screen — the two must render differently, or a
 * failed second page would blank out a first page the visitor already has.
 */
type Phase = "idle" | "loading" | "loadingMore" | "error" | "errorMore";

export function GiftsBrowser({ locale, initial }: { locale: string; initial: GiftsList }) {
  const t = useTranslations("web.gifts");
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  // `items`/`total` are accumulated pages, not one page — "Показать ещё"
  // appends in both browse and search mode. The first page is `initial`
  // (server-rendered) until a query is typed.
  const [items, setItems] = useState<GiftApp[]>(initial.items);
  const [total, setTotal] = useState(initial.total);
  const [phase, setPhase] = useState<Phase>("idle");

  // Guards a stale response — from rapid typing, or two "Показать ещё"
  // clicks — from landing after a newer request already has.
  const seqRef = useRef(0);

  // Debounce, mirroring `PromoField.tsx`'s `setTimeout` + cleanup pattern.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(raw.trim());
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw]);

  function fetchPage(offset: number, kind: "loading" | "loadingMore", forQuery: string): void {
    const seq = ++seqRef.current;
    setPhase(kind);
    searchGifts(locale, forQuery, offset)
      .then((page) => {
        if (seq !== seqRef.current) return;
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase(kind === "loading" ? "error" : "errorMore");
      });
  }

  // The settled query changed: reset accumulation. An empty query goes back
  // to the server-rendered `initial` page — no client fetch at all, same as
  // before — a non-empty query fetches its own first page. `searchGifts`
  // with an empty query hits the same plain `/gifts/catalog?offset=N`
  // endpoint browsing does, so "Показать ещё" on an untouched search box
  // pages through the same default listing `initial` came from.
  useEffect(() => {
    if (query === "") {
      seqRef.current += 1; // invalidate any fetch still in flight for the old query
      setItems(initial.items);
      setTotal(initial.total);
      setPhase("idle");
      return;
    }
    setItems([]);
    fetchPage(0, "loading", query);
    // `initial`/`locale` are stable for the component's lifetime (server
    // props); only the settled `query` should re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  function loadMore(): void {
    fetchPage(items.length, "loadingMore", query);
  }

  function retry(): void {
    if (phase === "error") fetchPage(0, "loading", query);
    else if (phase === "errorMore") fetchPage(items.length, "loadingMore", query);
  }

  const showSkeletons = phase === "loading" && items.length === 0;
  const showError = phase === "error" && items.length === 0;
  const canShowMore = items.length > 0 && items.length < total;

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

      {/* Reads as the catalogue count while browsing and the match count
          mid-search alike — `total` already carries both (2026-09-04
          review: the ~4k-game catalog gave no sense of scale, filtered or
          not). Hidden during a first-page fetch/error, where `total` is
          either stale or meaningless. */}
      {!showError && !showSkeletons && (
        <p className="text-tx-dim mt-3 text-[13px]">{t("search.resultCount", { count: total })}</p>
      )}

      {showError ? (
        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <p className="text-tx-mute text-[14px]">{t("search.error")}</p>
          <button
            type="button"
            onClick={retry}
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
      ) : items.length === 0 ? (
        <div className="mt-10 flex flex-col items-center gap-3 text-center">
          <p className="text-tx-mute text-[14px]">{t("search.empty")}</p>
          {/* A dead end used to be the whole state — nothing on screen
              offered anywhere to go next (2026-09-04 review). `#hot` is the
              hot-offers section on this same page (`HotOffers`), just above
              this component. */}
          <a href="#hot" className="text-primary text-[13px] font-semibold hover:underline">
            {t("search.emptyCta")}
          </a>
        </div>
      ) : (
        <>
          <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {items.map((app) => (
              <GiftCard key={app.app_id} app={app} locale={locale} />
            ))}
          </div>
          {phase === "errorMore" && (
            <div className="mt-4 flex flex-col items-center gap-2 text-center">
              <p className="text-tx-mute text-[14px]">{t("search.error")}</p>
              <button
                type="button"
                onClick={retry}
                className={buttonStyles({ variant: "ghost", size: "sm" })}
              >
                {t("search.retry")}
              </button>
            </div>
          )}
          {canShowMore && phase !== "errorMore" && (
            <div className="mt-8 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={phase === "loadingMore"}
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
