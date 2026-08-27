"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { pathFor } from "@/lib/seo";

export interface StoreChip {
  slug: string;
  label: string;
}

export interface StoreFilterItem {
  /** Stable key — the brand slug. Also set as the `key` on `node` itself. */
  key: string;
  /** Which chip shows this tile. */
  category: string;
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
}: {
  locale: string;
  chips: StoreChip[];
  items: StoreFilterItem[];
  emptyLabel: string;
}) {
  const [active, setActive] = useState("all");

  useEffect(() => {
    const cat = new URLSearchParams(window.location.search).get("cat");
    // An unknown ?cat= shows everything rather than an empty page — the same
    // fallback the server-side version applied.
    setActive(cat && items.some((i) => i.category === cat) ? cat : "all");
  }, [items]);

  const visible = active === "all" ? items : items.filter((i) => i.category === active);

  return (
    <>
      {chips.length > 1 && (
        <div className="mt-10 flex flex-wrap gap-2.5">
          {chips.map((f) => {
            const isActive = f.slug === active;
            const href =
              f.slug === "all"
                ? pathFor(locale, "/store")
                : pathFor(locale, `/store?cat=${f.slug}`);
            return (
              <Link
                key={f.slug}
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`inline-flex h-11 items-center rounded-full border px-4 text-sm font-semibold transition ${
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

      {visible.length > 0 ? (
        <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((item) => item.node)}
        </div>
      ) : (
        <p className="text-tx-mute mt-10 text-base">{emptyLabel}</p>
      )}
    </>
  );
}
