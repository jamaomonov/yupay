import Link from "next/link";
import { useTranslations } from "next-intl";

import { ScrollActiveIntoView } from "./ScrollActiveIntoView";
import { SkinCategoryIcon } from "./SkinCategoryIcon";

import type { SkinCategory, SkinFacets, SkinQuery, SkinQueryPatch } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { SKIN_CATEGORIES, skinQueryString } from "@/lib/skins";

const PATH = "/skins";

function tile(active: boolean): string {
  return `flex h-[64px] min-w-[72px] shrink-0 flex-col items-center justify-center gap-1 rounded-xl border px-2 text-[12px] font-semibold transition lg:min-w-0 ${
    active
      ? "border-primary bg-primary/10 text-primary"
      : "border-border bg-card text-tx-mute hover:border-border-2 hover:text-foreground"
  }`;
}

function chip(active: boolean): string {
  return `whitespace-nowrap rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition ${
    active
      ? "border-primary bg-primary/10 text-foreground"
      : "border-border text-tx-mute hover:border-border-2"
  }`;
}

/**
 * Categories as icon tiles (plain links — crawlable, no JS), and with a category
 * chosen, its weapons. The weapon list comes from the facets scoped to the
 * category, so it is the whole category, classics first; the chosen weapon is
 * always kept so it can be unset.
 */
export function SkinCategoryBar({
  query,
  facets,
  locale,
}: {
  query: SkinQuery;
  facets: SkinFacets;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const present = new Set(facets.categories.map((f) => f.value));
  const categories = SKIN_CATEGORIES.filter((c) => present.has(c));
  const listed = facets.weapons.map((f) => f.value);
  const weapons = query.category
    ? query.weapon && !listed.includes(query.weapon)
      ? [query.weapon, ...listed]
      : listed
    : [];
  const href = (patch: SkinQueryPatch) => pathFor(locale, PATH) + skinQueryString(query, patch);
  const tiles: (SkinCategory | "all")[] = ["all", ...categories];

  return (
    <nav className="space-y-2">
      <ScrollActiveIntoView className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:grid lg:grid-cols-12 lg:overflow-visible">
        {tiles.map((c) => {
          const active = c === "all" ? !query.category : query.category === c;
          return (
            <Link
              key={c}
              href={href(
                c === "all"
                  ? { category: undefined, weapon: undefined }
                  : { category: c, weapon: undefined },
              )}
              className={tile(active)}
              aria-current={active ? "page" : undefined}
            >
              <SkinCategoryIcon category={c} />
              <span className="truncate">{c === "all" ? t("all") : t(`category.${c}`)}</span>
            </Link>
          );
        })}
      </ScrollActiveIntoView>
      {(weapons.length > 1 || query.weapon !== undefined) && (
        <ScrollActiveIntoView className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:flex-wrap">
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
        </ScrollActiveIntoView>
      )}
    </nav>
  );
}
