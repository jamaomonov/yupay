import { Gift, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";

import type { CatalogPhase, GiftApp, GiftPage } from "@/lib/gifts";

import { SafeImage } from "@/components/ui/safe-image";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/currency";
import { accumulatePage, deriveCatalogView, fetchGiftsHot, fetchGiftsPage } from "@/lib/gifts";
import { useT } from "@/lib/i18n";
import { useDocumentTitle } from "@/lib/use-document-title";

/** Mirrors `GiftsBrowser`'s `SEARCH_DEBOUNCE_MS` on the web storefront —
 *  firing one request per keystroke would spend the catalog endpoint's rate
 *  budget on a single visit. */
const SEARCH_DEBOUNCE_MS = 400;
const SKELETON_COUNT = 6;

function discountLabel(app: GiftApp): number | null {
  return app.discount_percent != null && app.discount_percent > 0 ? app.discount_percent : null;
}

/** Exported for its own test coverage (see `GiftsCatalog.test.ts`) — this
 *  app's tests are node-env only, no jsdom/RTL, so the pure formatting piece
 *  is what's testable directly. */
export function priceText(app: GiftApp): string | null {
  if (app.price_uzs != null) return formatMoney(Math.round(Number(app.price_uzs)), "UZS");
  if (app.price_usd != null) return formatMoney(Number(app.price_usd), "USD");
  return null;
}

/**
 * Prefixes the catalogue card price with the localized "starting at" word.
 *
 * Catalogue rows carry the *default-zone reference* price
 * (`gifts/routes.py` documents this), never the per-package, per-country
 * figure the game page actually computes — without the prefix, a buyer taps
 * in at 1 250 000 and lands on 1 410 000, which reads as bait (2026-09-04
 * review).
 */
export function cardPriceLabel(app: GiftApp, fromWord: string): string | null {
  const price = priceText(app);
  return price === null ? null : `${fromWord} ${price}`;
}

/**
 * The hot-strip card — used to carry no price while the grid card two rows
 * below it did (2026-09-04 review): same content, two card designs. Now
 * shares `GiftCatalogCard`'s price row (`cardPriceLabel`) instead of ending
 * at the name.
 */
function HotCard({ app }: { app: GiftApp }) {
  const { t } = useT();
  const discount = discountLabel(app);
  const price = cardPriceLabel(app, t("gifts.card.from"));
  return (
    <Link
      href={`/gifts/${String(app.app_id)}`}
      className="flex w-[140px] shrink-0 flex-col overflow-hidden rounded-2xl border"
      style={{ borderColor: "hsl(var(--border))", background: "hsl(var(--surface-2))" }}
    >
      <div className="relative aspect-[16/9] w-full overflow-hidden bg-black/20">
        {app.image && <SafeImage src={app.image} className="h-full w-full object-cover" />}
        {discount !== null && (
          <span className="bg-primary absolute right-1.5 top-1.5 rounded-full px-1.5 py-0.5 text-[9px] font-bold text-black">
            {t("gifts.badge.discount", { percent: discount })}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2">
        <p className="line-clamp-2 text-[11px] font-semibold leading-snug text-white">{app.name}</p>
        {price !== null && (
          <p className="mt-auto pt-0.5 font-mono text-[12px] font-bold text-white">{price}</p>
        )}
      </div>
    </Link>
  );
}

function GiftCatalogCard({ app }: { app: GiftApp }) {
  const { t, tn } = useT();
  const discount = discountLabel(app);
  const price = cardPriceLabel(app, t("gifts.card.from"));
  return (
    <Link
      href={`/gifts/${String(app.app_id)}`}
      className="flex flex-col overflow-hidden rounded-2xl border"
      style={{ borderColor: "hsl(var(--border))", background: "hsl(var(--surface-2))" }}
    >
      <div className="relative aspect-[16/9] w-full overflow-hidden bg-black/20">
        {app.image && <SafeImage src={app.image} className="h-full w-full object-cover" />}
        {discount !== null && (
          <span className="bg-primary absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-bold text-black">
            {t("gifts.badge.discount", { percent: discount })}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2.5">
        <p className="line-clamp-2 text-[12px] font-semibold leading-snug text-white">{app.name}</p>
        {/* `white/40` measured 3.68–3.81:1 on this app's surfaces — below the
            4.5:1 floor for 10px text (2026-09-04 review). `white/50` clears it. */}
        <p className="text-[10px] text-white/50">
          {tn("gifts.card.editions", app.packages_count)}
          {" · "}
          {tn("gifts.card.dlc", app.dlc_count)}
        </p>
        {price !== null && (
          <p className="mt-auto pt-1 font-mono text-[13px] font-bold text-white">{price}</p>
        )}
      </div>
    </Link>
  );
}

/**
 * Loading placeholder shaped like the card it's standing in for — a 16/9
 * image block plus a two-line text block, instead of a bare `aspect-[3/4]`
 * rectangle that bore no resemblance to the eventual `GiftCatalogCard`
 * (2026-09-04 review): content jumped on every load as the real card's very
 * different proportions landed. Mirrors `TopUp.tsx`'s shape-aware
 * `PackagesSkeleton`.
 */
function GiftCardSkeleton() {
  return (
    <div
      className="overflow-hidden rounded-2xl border"
      style={{ borderColor: "hsl(var(--border))", background: "hsl(var(--surface-2))" }}
    >
      <Skeleton className="aspect-[16/9] w-full rounded-none" />
      <div className="space-y-1.5 p-2.5">
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-3 w-2/5" />
        <Skeleton className="mt-1 h-3.5 w-1/2" />
      </div>
    </div>
  );
}

function ComingSoon() {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <div
        className="flex h-14 w-14 items-center justify-center rounded-2xl border"
        style={{ background: "hsl(var(--surface-2))", borderColor: "hsl(var(--border) / 0.6)" }}
      >
        <Gift className="text-primary h-7 w-7" strokeWidth={1.75} aria-hidden="true" />
      </div>
      <p className="max-w-[260px] text-sm text-white/50">{t("gifts.comingSoon")}</p>
    </div>
  );
}

export default function GiftsCatalog() {
  const { t } = useT();
  useDocumentTitle(t("gifts.docTitle"));

  const [hot, setHot] = useState<GiftApp[]>([]);
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<GiftPage>({ items: [], total: 0 });
  const [phase, setPhase] = useState<CatalogPhase>("loading");
  // Set once, the first time the default (no-search) listing comes back with
  // zero items — the whole `/gifts/*` surface 404s while the feature flag is
  // off, and every fetcher swallows that into an empty result. Distinguishes
  // "this feature isn't live yet" from a search that genuinely found nothing.
  const [firstLoadEmpty, setFirstLoadEmpty] = useState(false);

  const seqRef = useRef(0);

  useEffect(() => {
    fetchGiftsHot()
      .then(setHot)
      .catch(() => {
        // Hot strip is decorative — leave it empty on failure.
      });
  }, []);

  function fetchPage(offset: number, kind: "loading" | "loadingMore", forQuery: string): void {
    const seq = ++seqRef.current;
    setPhase(kind);
    fetchGiftsPage(offset, forQuery)
      .then((result) => {
        if (seq !== seqRef.current) return;
        setPage((prev) => accumulatePage(prev, result, offset));
        if (offset === 0 && forQuery === "" && result.items.length === 0) {
          setFirstLoadEmpty(true);
        }
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase(kind === "loading" ? "error" : "errorMore");
      });
  }

  // Debounce, mirroring `GiftsBrowser`'s `setTimeout` + cleanup pattern.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(raw.trim());
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [raw]);

  // Initial mount + every settled query change fetches its own first page.
  useEffect(() => {
    fetchPage(0, "loading", query);
  }, [query]);

  function loadMore(): void {
    fetchPage(page.items.length, "loadingMore", query);
  }

  function retry(): void {
    if (phase === "error") fetchPage(0, "loading", query);
    else if (phase === "errorMore") fetchPage(page.items.length, "loadingMore", query);
  }

  const searching = raw.trim() !== "";
  const { showSkeletons, showError, showComingSoon, showEmpty, canShowMore } = deriveCatalogView({
    phase,
    itemsLength: page.items.length,
    total: page.total,
    firstLoadEmpty,
    hasQuery: query !== "",
  });

  return (
    // CSS keyframe (`.yp-fade-in`, `index.css`) replaces the old
    // framer-motion fade+slide (2026-09-04 review) — see `GiftGame.tsx`'s
    // identical comment for the reasoning and the `prefers-reduced-motion`
    // story.
    <div className="yp-fade-in space-y-5 pb-2">
      <div className="px-4 pt-4">
        <h1 className="text-xl font-bold leading-tight tracking-tight text-white">
          {t("gifts.title")}
        </h1>
        <p className="text-body-muted mt-0.5 text-xs">{t("gifts.subtitle")}</p>
      </div>

      {hot.length > 0 && !searching && (
        <div className="px-4">
          <span className="text-sm font-semibold text-white">{t("gifts.hot.title")}</span>
          <div className="no-scrollbar mt-3 flex gap-3 overflow-x-auto">
            {hot.map((app) => (
              <HotCard key={app.app_id} app={app} />
            ))}
          </div>
        </div>
      )}

      <div className="px-4">
        <div className="relative">
          <Search
            size={15}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2"
            style={{ color: "hsl(var(--primary) / 0.7)" }}
            aria-hidden="true"
          />
          <input
            type="search"
            role="searchbox"
            value={raw}
            onChange={(e) => {
              setRaw(e.target.value);
            }}
            placeholder={t("gifts.search.placeholder")}
            aria-label={t("gifts.search.placeholder")}
            className="placeholder:text-body-faint w-full rounded-xl py-2.5 pl-9 pr-3 text-sm text-white outline-none"
            style={{
              background: "hsl(var(--surface-2))",
              border: "1px solid hsl(var(--border))",
            }}
          />
        </div>
      </div>

      <div className="px-4">
        {showSkeletons ? (
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: SKELETON_COUNT }, (_, i) => (
              <GiftCardSkeleton key={i} />
            ))}
          </div>
        ) : showComingSoon ? (
          <ComingSoon />
        ) : showError ? (
          <div className="flex flex-col items-center gap-3 py-14 text-center">
            <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
            <button type="button" onClick={retry} className="text-primary text-sm font-semibold">
              {t("common.retry")}
            </button>
          </div>
        ) : showEmpty ? (
          <p className="py-14 text-center text-sm text-white/50">{t("gifts.search.empty")}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              {page.items.map((app) => (
                <GiftCatalogCard key={app.app_id} app={app} />
              ))}
            </div>
            {phase === "errorMore" && (
              <div className="mt-4 flex flex-col items-center gap-2 text-center">
                <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
                <button
                  type="button"
                  onClick={retry}
                  className="text-primary text-sm font-semibold"
                >
                  {t("common.retry")}
                </button>
              </div>
            )}
            {canShowMore && phase !== "errorMore" && (
              <div className="mt-5 flex justify-center">
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={phase === "loadingMore"}
                  className="rounded-xl px-4 py-2 text-sm font-semibold text-white/70 disabled:opacity-50"
                  style={{
                    background: "hsl(var(--surface-2))",
                    border: "1px solid hsl(var(--border))",
                  }}
                >
                  {t("gifts.search.showMore")}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
