"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { pushAnalyticsEvent, viewItemListEvent } from "@/lib/analytics-events";
import { inputStyles } from "@/lib/input";
import { pathFor } from "@/lib/seo";

/** The icon shelf: three across on a phone, eight on a desktop. */
const GRID =
  "mt-4 grid grid-cols-3 gap-x-3 gap-y-6 sm:grid-cols-4 sm:gap-x-5 md:grid-cols-6 lg:grid-cols-8";

export interface StoreChip {
  slug: string;
  label: string;
}

export interface StoreFilterItem {
  /** Stable key — the brand slug. Also set as the `key` on `node` itself. */
  key: string;
  /** Which chip shows this tile. */
  category: string;
  /** What the search box matches against. */
  name: string;
  /**
   * The tile, already rendered on the server AND already carrying its React
   * key. It is rendered as the direct grid child — never wrapped.
   *
   * `BrandTile` is a `<Link>`, so a `<a>`, and an `<a>` is `display: inline`
   * by default: height simply does not apply to it. As a direct grid item the
   * grid blockifies it and its `h-[240px]` takes effect. Wrapping it in a
   * `<div>` — which an earlier version of this file did, purely to hang the
   * key on — left the anchor inline, so the tile had no height, the `fill`
   * image had nothing to fill, and every card collapsed into overlapping text.
   */
  node: ReactNode;
}

/**
 * Category chips plus the brand grid they filter.
 *
 * Filtering used to happen on the server, from `searchParams`. Reading those
 * opts the whole route into dynamic rendering, so `/store` was re-rendered on
 * the origin for every visitor and its own `revalidate = 300` was quietly
 * ignored. The page fetches the entire catalog either way and only the visible
 * subset differs, so the server output does not really depend on `?cat=`.
 *
 * The query string is read in an effect rather than through
 * `useSearchParams()`, and that is the whole trick. `useSearchParams` suspends
 * during prerender: the first version of this component used it inside a
 * `<Suspense>` boundary, and the prerendered HTML came back with the fallback
 * — no chips, no tiles, an empty catalogue for crawlers and for the first
 * paint, with the whole grid shipped as serialized props instead. Reading
 * `location.search` after mount keeps every tile in the server-rendered DOM,
 * which is what SEO and LCP actually need.
 *
 * The cost is one extra render on a direct hit to `?cat=x`: the page paints
 * with everything shown and settles a frame later. That is the right trade
 * against an origin render per visitor, and it is invisible on the "all" case
 * that most visitors arrive at.
 *
 * The tiles stay server components — they are passed in pre-rendered rather
 * than re-created here, so `BrandTile` keeps its server-side translations and
 * none of it lands in the browser bundle.
 */
export function StoreFilter({
  locale,
  chips,
  items,
  emptyLabel,
  searchLabel,
}: {
  locale: string;
  chips: StoreChip[];
  items: StoreFilterItem[];
  emptyLabel: string;
  /** Placeholder and accessible name of the search box. */
  searchLabel: string;
}) {
  const [active, setActive] = useState("all");
  const [query, setQuery] = useState("");
  // The list GA4's `view_item_list` last went out for, so a re-render of the
  // same category never sends it again.
  const listSent = useRef<string | null>(null);

  useEffect(() => {
    const cat = new URLSearchParams(window.location.search).get("cat");
    // An unknown ?cat= shows everything rather than an empty page — the same
    // fallback the server-side version applied.
    const list = cat && items.some((i) => i.category === cat) ? cat : "all";
    setActive(list);
    // Sent from here, where the category is settled, not from a render with
    // the pre-mount "all" a `?cat=` hit starts on. The search box is not a
    // list view and sends nothing: what is typed there is free text.
    if (listSent.current !== list) {
      listSent.current = list;
      const shown = list === "all" ? items : items.filter((i) => i.category === list);
      pushAnalyticsEvent(
        viewItemListEvent(
          list,
          chips.find((c) => c.slug === list)?.label ?? list,
          shown.map((i) => ({ slug: i.key, name: i.name })),
        ),
      );
    }
  }, [items, chips]);

  // A search looks across every category: someone typing «pubg» while
  // «Подарочные карты» is picked still means PUBG.
  const needle = query.trim().toLocaleLowerCase();
  const visible = needle
    ? items.filter((i) => i.name.toLocaleLowerCase().includes(needle))
    : active === "all"
      ? items
      : items.filter((i) => i.category === active);

  // «Все» with nothing typed reads as a shelf per category; a picked category
  // or a search is one flat grid.
  const grouped = !needle && active === "all";
  const sections = grouped
    ? chips
        .filter((c) => c.slug !== "all")
        .map((c) => ({ chip: c, items: items.filter((i) => i.category === c.slug) }))
        .filter((g) => g.items.length > 0)
    : [];
  // A brand whose category has no chip still shows, on a shelf of its own.
  const unshelved = grouped
    ? items.filter((i) => !chips.some((c) => c.slug !== "all" && c.slug === i.category))
    : [];

  return (
    <>
      {/* Pinned under the fixed 72px header at every width: the search and the
          categories are how a buyer moves through the shelf. */}
      <div className="bg-bg/90 border-border/60 sticky top-[72px] z-20 -mx-6 mt-6 border-b px-6 py-3 backdrop-blur sm:-mx-10 sm:px-10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
          <input
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            placeholder={searchLabel}
            aria-label={searchLabel}
            className={inputStyles({ className: "h-11 sm:max-w-[340px]" })}
          />
          {chips.length > 1 && (
            <div className="-mx-6 flex gap-2 overflow-x-auto px-6 [scrollbar-width:none] sm:mx-0 sm:px-0">
              {chips.map((f) => {
                const isActive = f.slug === active && !needle;
                const href =
                  f.slug === "all"
                    ? pathFor(locale, "/store")
                    : pathFor(locale, `/store?cat=${f.slug}`);
                return (
                  <Link
                    key={f.slug}
                    href={href}
                    onClick={() => {
                      setQuery("");
                    }}
                    aria-current={isActive ? "page" : undefined}
                    className={`inline-flex h-10 shrink-0 items-center rounded-full border px-4 text-sm font-semibold transition ${
                      isActive
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-muted text-tx-mute hover:text-foreground"
                    }`}
                  >
                    {f.label}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="text-tx-mute mt-10 text-base">{emptyLabel}</p>
      ) : grouped ? (
        <>
          {sections.map((g) => (
            <section
              key={g.chip.slug}
              className="mt-8 sm:mt-10"
              aria-labelledby={`shelf-${g.chip.slug}`}
            >
              <h2
                id={`shelf-${g.chip.slug}`}
                className="flex items-baseline gap-2 text-lg font-bold"
              >
                {g.chip.label}
                <span className="text-tx-dim text-sm font-semibold">{g.items.length}</span>
              </h2>
              <div className={GRID}>{g.items.map((item) => item.node)}</div>
            </section>
          ))}
          {unshelved.length > 0 && (
            <div className={`${GRID} mt-8`}>{unshelved.map((item) => item.node)}</div>
          )}
        </>
      ) : (
        <div className={`${GRID} mt-8`}>{visible.map((item) => item.node)}</div>
      )}
    </>
  );
}
