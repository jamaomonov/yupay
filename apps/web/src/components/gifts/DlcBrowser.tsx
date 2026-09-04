"use client";

import { ChevronLeft, ChevronRight, Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { GiftCard } from "./GiftCard";

import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/lib/button";
import { fetchGiftDlc, type GiftApp } from "@/lib/gifts";

/**
 * "Requires the base game" note for a DLC's own product page. `DlcBrowser`
 * below links every DLC entry straight to its own `/store/steam-gifts/
 * {app_id}` page (via `GiftCard`), and nothing else on that page said a DLC
 * gift only works if the recipient already owns the base game — a
 * delivered, unusable gift. Renders only when `type` marks the app as DLC
 * (`GiftAppOut.type`, "dlc" vs. "game"); no wire field for the parent
 * game's name exists yet, so the copy stays generic rather than growing one
 * just for this note.
 */
export function DlcNote({ type }: { type: string }) {
  const t = useTranslations("web.gifts.game");
  if (type !== "dlc") return null;
  return (
    <div className="border-border bg-muted/40 rounded-lg border p-3 text-[13px]">
      <p className="text-foreground flex items-start gap-1.5">
        <Info size={14} className="text-tx-dim mt-0.5 shrink-0" aria-hidden="true" />
        <span className="text-tx-mute leading-snug">{t("dlcNote")}</span>
      </p>
    </div>
  );
}

/** Matches the API's default `limit` for `/gifts/catalog/{appId}/dlc` — see
 *  `gifts/routes.py::get_catalog_app_dlc`. */
const PAGE_SIZE = 24;
/** Mirrors `GiftsBrowser`'s search debounce. */
const SEARCH_DEBOUNCE_MS = 400;
const SKELETON_COUNT = 8;

type Phase = "idle" | "loading" | "error";

/**
 * Collapsed-by-default DLC list for one game: a single "DLC: N — показать"
 * toggle that, once tapped, mounts a search box and a paged grid backed by
 * `fetchGiftDlc`. Unlike `GiftsBrowser`'s "Показать ещё" accumulation, a new
 * page here *replaces* the one on screen — this never renders more than one
 * page (24 rows) at a time, which is what keeps a game with hundreds of DLC
 * entries from turning this block into its own infinite-scroll catalog.
 * Each row is the same `GiftCard` the top-level browser uses, so it links
 * straight to that DLC's own `/store/steam-gifts/{app_id}` page.
 */
export function DlcBrowser({
  appId,
  total,
  locale,
}: {
  appId: number;
  total: number;
  locale: string;
}) {
  const t = useTranslations("web.gifts");
  const [expanded, setExpanded] = useState(false);
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<GiftApp[]>([]);
  const [resultTotal, setResultTotal] = useState(total);
  const [phase, setPhase] = useState<Phase>("idle");

  // Guards a stale response landing after a newer request already has —
  // same pattern `GiftsBrowser` uses.
  const seqRef = useRef(0);
  // The last query a fetch actually ran for, so the "query changed" effect
  // below can tell a genuine edit from the debounce timer re-settling on the
  // same value `expand()` already fetched.
  const fetchedQueryRef = useRef<string | null>(null);

  useEffect(() => {
    if (!expanded) return;
    const timer = setTimeout(() => {
      setQuery(raw.trim());
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw, expanded]);

  function fetchPage(nextOffset: number, forQuery: string): void {
    const seq = ++seqRef.current;
    fetchedQueryRef.current = forQuery;
    setPhase("loading");
    fetchGiftDlc(locale, appId, forQuery, nextOffset)
      .then((page) => {
        if (seq !== seqRef.current) return;
        setItems(page.items);
        setResultTotal(page.total);
        setOffset(nextOffset);
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase("error");
      });
  }

  function expand(): void {
    setExpanded(true);
    fetchPage(0, "");
  }

  // The settled query changed while expanded → fetch its first page. A
  // no-op the moment `expanded` flips true (the debounce timer re-settling
  // on the same `""` `expand()` already fetched) and on every render where
  // the query hasn't actually moved since the last fetch.
  useEffect(() => {
    if (!expanded || fetchedQueryRef.current === query) return;
    fetchPage(0, query);
    // `appId`/`locale` are stable props for this component's lifetime; only
    // the settled `query` should re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, expanded]);

  // No DLC at all — nothing to collapse into a toggle for.
  if (total <= 0) return null;

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={expand}
        aria-expanded={false}
        className={buttonStyles({ variant: "ghost", size: "sm" })}
      >
        {t("dlc.toggle", { count: total })}
      </button>
    );
  }

  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < resultTotal;
  // More than one page exists at all — computed from `resultTotal`, not
  // `items.length`, so this stays true (and the pager stays mounted) through
  // a `phase === "loading"` fetch: `items`/`offset`/`resultTotal` are only
  // overwritten once that fetch's `.then()` lands, so a page turn shows the
  // pager as disabled instead of unmounting it out from under the buyer's
  // thumb mid-tap (2026-09-04 review).
  const hasMultiplePages = resultTotal > PAGE_SIZE;
  const showPager = phase !== "error" && hasMultiplePages;
  const pagerBusy = phase === "loading";
  const rangeFrom = offset + 1;
  const rangeTo = Math.min(offset + PAGE_SIZE, resultTotal);

  return (
    <div className="mt-4">
      <input
        type="search"
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
        }}
        placeholder={t("dlc.searchPlaceholder")}
        aria-label={t("dlc.searchPlaceholder")}
        className="border-border bg-card rounded-btn h-10 w-full max-w-[360px] border px-3 text-sm"
      />

      {phase === "error" ? (
        <div className="mt-6 flex flex-col items-center gap-2 text-center">
          <p className="text-tx-mute text-[14px]">{t("search.error")}</p>
          <button
            type="button"
            onClick={() => {
              fetchPage(offset, query);
            }}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            {t("search.retry")}
          </button>
        </div>
      ) : phase === "loading" ? (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: SKELETON_COUNT }, (_, i) => (
            <Skeleton key={i} className="aspect-[3/4] rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-tx-mute mt-6 text-center text-[14px]">{t("search.empty")}</p>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((app) => (
            <GiftCard key={app.app_id} app={app} locale={locale} />
          ))}
        </div>
      )}

      {showPager && (
        <div className="mt-4 flex items-center justify-center gap-3">
          <button
            type="button"
            disabled={!canPrev || pagerBusy}
            onClick={() => {
              fetchPage(offset - PAGE_SIZE, query);
            }}
            aria-label={t("dlc.prevPage")}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className="text-tx-dim text-[12px] tabular-nums">
            {t("dlc.pageRange", { from: rangeFrom, to: rangeTo, total: resultTotal })}
          </span>
          <button
            type="button"
            disabled={!canNext || pagerBusy}
            onClick={() => {
              fetchPage(offset + PAGE_SIZE, query);
            }}
            aria-label={t("dlc.nextPage")}
            className={buttonStyles({ variant: "ghost", size: "sm" })}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
