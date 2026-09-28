import Link from "next/link";
import { useTranslations } from "next-intl";

import type { SkinQueryPatch, SkinFacets, SkinItem, SkinQuery } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { SKIN_CATEGORIES, skinQueryString } from "@/lib/skins";

const PATH = "/skins";

function chip(active: boolean): string {
  return `whitespace-nowrap rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition ${
    active
      ? "border-primary bg-primary/10 text-foreground"
      : "border-border text-tx-mute hover:border-border-2"
  }`;
}

/**
 * Categories as plain links (crawlable, no JS). With a category chosen, a
 * second row offers its weapons. The facets endpoint counts weapons across the
 * whole catalogue, so the row is narrowed to weapons present on the current
 * page — good enough while pages hold 48 items; a per-category facet is the
 * upgrade if it ever reads as incomplete.
 */
export function SkinCategoryBar({
  query,
  facets,
  locale,
  items,
}: {
  query: SkinQuery;
  facets: SkinFacets;
  locale: string;
  items: SkinItem[];
}) {
  const t = useTranslations("web.skins");
  const present = new Set(facets.categories.map((f) => f.value));
  const categories = SKIN_CATEGORIES.filter((c) => present.has(c));
  // The chosen weapon always stays on the row, even when the page holds none of
  // it (a price filter emptied it) — otherwise there is no chip to unset it with.
  const onPage = items.map((i) => i.weapon).filter((w): w is string => w !== null);
  const weapons = query.category
    ? [...new Set(query.weapon ? [...onPage, query.weapon] : onPage)].sort()
    : [];
  const href = (patch: SkinQueryPatch) => pathFor(locale, PATH) + skinQueryString(query, patch);

  return (
    <nav className="space-y-2">
      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        <Link
          href={href({ category: undefined, weapon: undefined })}
          className={chip(!query.category)}
        >
          {t("all")}
        </Link>
        {categories.map((c) => (
          <Link
            key={c}
            href={href({ category: c, weapon: undefined })}
            className={chip(query.category === c)}
            aria-current={query.category === c ? "page" : undefined}
          >
            {t(`category.${c}`)}
          </Link>
        ))}
      </div>
      {(weapons.length > 1 || query.weapon !== undefined) && (
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
          {weapons.map((w) => (
            <Link
              key={w}
              href={href({ weapon: query.weapon === w ? undefined : w })}
              className={chip(query.weapon === w)}
              aria-current={query.weapon === w ? "page" : undefined}
            >
              {w}
            </Link>
          ))}
        </div>
      )}
    </nav>
  );
}
