import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";

import type { GiftApp } from "@/lib/gifts";

import { SafeImage } from "@/components/ui/safe-image";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchGiftDlc } from "@/lib/gifts";
import { useT } from "@/lib/i18n";

/** Matches the API's default DLC page size (`gifts/routes.py`). */
const DLC_PAGE_SIZE = 24;
const DLC_SEARCH_DEBOUNCE_MS = 400;

type DlcPhase = "idle" | "loading" | "error";

/**
 * Collapsed-by-default DLC browser for one game: its own search box + a
 * paged (24-per-page) grid, opened from `GiftGame`'s "DLC: N — показать"
 * toggle. Unlike the catalog's "Показать ещё" accumulation, a new page here
 * *replaces* the one on screen — mirrors `DlcBrowser` on the web storefront.
 *
 * Extracted out of `GiftGame.tsx` (2026-09-03 review) purely to keep that
 * file near the repo's TS file-length budget — no behaviour change.
 */
export function DlcSheet({
  open,
  onOpenChange,
  appId,
  total,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  appId: number;
  total: number;
}) {
  const { t } = useT();
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<GiftApp[]>([]);
  const [resultTotal, setResultTotal] = useState(total);
  const [phase, setPhase] = useState<DlcPhase>("idle");
  const seqRef = useRef(0);

  function fetchPage(nextOffset: number, forQuery: string): void {
    const seq = ++seqRef.current;
    setPhase("loading");
    fetchGiftDlc(appId, forQuery, nextOffset)
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

  // Fresh mount each time the sheet opens — load the unfiltered first page.
  useEffect(() => {
    if (!open) return;
    setRaw("");
    setQuery("");
    fetchPage(0, "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, appId]);

  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      setQuery(raw.trim());
    }, DLC_SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw, open]);

  const isFirstRun = useRef(true);
  useEffect(() => {
    if (!open) return;
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    fetchPage(0, query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const canPrev = offset > 0;
  const canNext = offset + DLC_PAGE_SIZE < resultTotal;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[80vh] overflow-y-auto rounded-t-3xl">
        <SheetHeader>
          <SheetTitle>{t("gifts.dlc.toggle", { count: total })}</SheetTitle>
        </SheetHeader>
        <input
          type="search"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
          }}
          placeholder={t("gifts.dlc.searchPlaceholder")}
          aria-label={t("gifts.dlc.searchPlaceholder")}
          className="mt-3 h-10 w-full rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
          style={{ borderColor: "hsl(var(--border))" }}
        />

        {phase === "error" ? (
          <div className="mt-6 flex flex-col items-center gap-2 text-center">
            <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
            <button
              type="button"
              onClick={() => {
                fetchPage(offset, query);
              }}
              className="text-primary text-sm font-semibold"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : phase === "loading" ? (
          <div className="mt-4 grid grid-cols-2 gap-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="aspect-[16/9] rounded-xl" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="mt-6 text-center text-sm text-white/50">{t("gifts.search.empty")}</p>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-3">
            {items.map((app) => (
              <Link
                key={app.app_id}
                href={`/gifts/${String(app.app_id)}`}
                onClick={() => {
                  onOpenChange(false);
                }}
                className="flex flex-col overflow-hidden rounded-xl border"
                style={{ borderColor: "hsl(var(--border))" }}
              >
                <div className="aspect-[16/9] w-full overflow-hidden bg-black/20">
                  {app.image && (
                    <SafeImage src={app.image} className="h-full w-full object-cover" />
                  )}
                </div>
                <p className="line-clamp-2 p-2 text-[12px] font-semibold text-white">{app.name}</p>
              </Link>
            ))}
          </div>
        )}

        {phase === "idle" && items.length > 0 && (canPrev || canNext) && (
          <div className="mt-4 flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={!canPrev}
              onClick={() => {
                fetchPage(offset - DLC_PAGE_SIZE, query);
              }}
              aria-label={t("gifts.dlc.prevPage")}
              className="flex h-8 w-8 items-center justify-center rounded-full disabled:opacity-30"
              style={{ background: "hsl(var(--surface-2))" }}
            >
              <ChevronLeft size={16} className="text-white/70" />
            </button>
            <button
              type="button"
              disabled={!canNext}
              onClick={() => {
                fetchPage(offset + DLC_PAGE_SIZE, query);
              }}
              aria-label={t("gifts.dlc.nextPage")}
              className="flex h-8 w-8 items-center justify-center rounded-full disabled:opacity-30"
              style={{ background: "hsl(var(--surface-2))" }}
            >
              <ChevronRight size={16} className="text-white/70" />
            </button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
