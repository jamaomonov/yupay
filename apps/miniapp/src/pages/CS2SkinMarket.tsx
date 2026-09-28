import { parseSkinQuery, skinQueryString } from "@yupay/utils";
import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";

import type { SkinFacets, SkinItem, SkinQueryPatch, SkinSort } from "@yupay/utils";

import { SkinCard } from "@/components/skins/SkinCard";
import { SkinChips } from "@/components/skins/SkinChips";
import { SkinFilterSheet } from "@/components/skins/SkinFilterSheet";
import { SkinsComingSoon } from "@/components/skins/SkinsComingSoon";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { fetchSkinFacets, fetchSkinsPage } from "@/lib/skins";
import { accumulateSkins } from "@/lib/skins-view";
import { useDocumentTitle } from "@/lib/use-document-title";

const PATH = "/cs2-market";
const SEARCH_DEBOUNCE_MS = 400; // mirrors GiftsCatalog: one request per pause, not per key
const SORTS: readonly SkinSort[] = ["popular", "price", "-price", "discount"];
const FIELD = { background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" };

type Phase = "loading" | "idle" | "loadingMore" | "error" | "errorMore";

/**
 * The CS2 skins catalogue. Filters live in the URL query, so Telegram's back
 * button from an item returns to the same filtered grid; filter changes
 * replace the history entry rather than stacking one per tap. While the API
 * has skins switched off, the facets 404 and the "coming soon" screen shows.
 */
export default function CS2SkinMarket() {
  const { t } = useT();
  useDocumentTitle(t("cs2.docTitle"));
  const search = useSearch();
  const [, navigate] = useLocation();
  const query = useMemo(() => {
    const { cursor: _cursor, ...q } = parseSkinQuery(
      Object.fromEntries(new URLSearchParams(search)),
    );
    return q;
  }, [search]);
  const key = skinQueryString(query);

  const [facets, setFacets] = useState<SkinFacets | null | undefined>(undefined);
  const [items, setItems] = useState<SkinItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [raw, setRaw] = useState(query.q ?? "");
  const seq = useRef(0);

  const change = (patch: SkinQueryPatch) => {
    navigate(PATH + skinQueryString(query, patch), { replace: true });
  };

  useEffect(() => {
    fetchSkinFacets()
      .then(setFacets)
      .catch(() => {
        setFacets(undefined); // chips fall back to every category
      });
  }, []);

  function load(append: boolean): void {
    const mine = ++seq.current;
    setPhase(append ? "loadingMore" : "loading");
    fetchSkinsPage(append && cursor ? { ...query, cursor } : query)
      .then((page) => {
        if (mine !== seq.current) return;
        setItems((prev) => accumulateSkins(prev, page.items, append));
        setCursor(page.next_cursor);
        setPhase("idle");
      })
      .catch(() => {
        if (mine !== seq.current) return;
        setPhase(append ? "errorMore" : "error");
      });
  }

  useEffect(() => {
    load(false);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps -- `key` is the query

  useEffect(() => {
    const text = raw.trim();
    if (text === (query.q ?? "")) return;
    const timer = setTimeout(
      () => change({ q: text === "" ? undefined : text }),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [raw]); // eslint-disable-line react-hooks/exhaustive-deps -- debounce on typing only

  if (facets === null) return <SkinsComingSoon />;

  return (
    <div className="yp-fade-in space-y-4 pb-2">
      <div className="px-4 pt-4">
        <h1 className="text-xl font-bold leading-tight tracking-tight text-white">
          {t("cs2.title")}
        </h1>
      </div>

      <div className="space-y-3 px-4">
        <div className="relative">
          <Search
            size={15}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2"
            style={{ color: "hsl(var(--primary) / 0.7)" }}
            aria-hidden="true"
          />
          <input
            type="search"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={t("cs2.searchPlaceholder")}
            aria-label={t("cs2.searchPlaceholder")}
            className="placeholder:text-body-faint w-full rounded-xl py-2.5 pl-9 pr-3 text-sm text-white outline-none"
            style={FIELD}
          />
        </div>
        <div className="flex gap-2">
          <SkinFilterSheet query={query} facets={facets} onChange={change} />
          <select
            aria-label={t("cs2.sortLabel")}
            value={query.sort}
            onChange={(e) => change({ sort: e.target.value as SkinSort })} // options are SORTS
            className="min-w-0 flex-1 rounded-xl px-3 py-2.5 text-sm text-white outline-none"
            style={FIELD}
          >
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {t(`cs2.sort.${s}`)}
              </option>
            ))}
          </select>
        </div>
        <SkinChips query={query} facets={facets} items={items} onChange={change} />
      </div>

      <div className="px-4">
        {phase === "loading" ? (
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="aspect-[3/4] rounded-2xl" />
            ))}
          </div>
        ) : phase === "error" ? (
          <Retry label={t("cs2.error")} onRetry={() => load(false)} />
        ) : items.length === 0 ? (
          <p className="py-14 text-center text-sm text-white/50">{t("cs2.empty")}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              {items.map((item) => (
                <SkinCard key={item.slug} item={item} />
              ))}
            </div>
            {phase === "errorMore" ? (
              <Retry label={t("cs2.error")} onRetry={() => load(true)} />
            ) : (
              cursor !== null && (
                <div className="mt-5 flex justify-center">
                  <button
                    type="button"
                    onClick={() => load(true)}
                    disabled={phase === "loadingMore"}
                    className="rounded-xl px-4 py-2 text-sm font-semibold text-white/70 disabled:opacity-50"
                    style={FIELD}
                  >
                    {t("cs2.loadMore")}
                  </button>
                </div>
              )
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Retry({ label, onRetry }: { label: string; onRetry: () => void }) {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-sm text-white/50">{label}</p>
      <button type="button" onClick={onRetry} className="text-primary text-sm font-semibold">
        {t("common.retry")}
      </button>
    </div>
  );
}
