import { SKIN_CATEGORIES } from "@yupay/utils";
import { useEffect, useRef } from "react";

import type { SkinCategory, SkinQuery, SkinQueryPatch } from "@yupay/utils";
import type { ScopedFacets } from "@/lib/skins-view";

import { SkinCategoryIcon } from "@/components/skins/SkinCategoryIcon";
import { useT } from "@/lib/i18n";
import { visibleWeapons } from "@/lib/skins-view";
import { haptic } from "@/lib/telegram";

const SURFACE = { background: "hsl(var(--surface-2))", borderColor: "hsl(var(--border))" };
const ACTIVE = { background: "hsl(var(--primary) / 0.12)" };

/** Scroll the row's pressed item into the middle — a far category sits off-screen otherwise. */
function useCentredActive(dep: string | undefined) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = ref.current;
    const active = row?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!row || !active) return;
    row.scrollLeft = active.offsetLeft - (row.clientWidth - active.offsetWidth) / 2;
  }, [dep]);
  return ref;
}

/**
 * Category tiles with their silhouette icons and — with a category chosen — its
 * weapons. The weapons come from the facets scoped to the category (the whole
 * category, classics first); the chosen weapon always stays so it can be unset.
 */
export function SkinChips({
  query,
  scoped,
  onChange,
}: {
  query: SkinQuery;
  scoped: ScopedFacets | undefined;
  onChange: (patch: SkinQueryPatch) => void;
}) {
  const facets = scoped?.facets;
  const { t } = useT();
  const present = facets ? new Set(facets.categories.map((f) => f.value)) : null;
  const tiles: (SkinCategory | "all")[] = [
    "all",
    ...SKIN_CATEGORIES.filter((c) => present === null || present.has(c)),
  ];
  const weapons = visibleWeapons(query, scoped);
  const tileRow = useCentredActive(query.category);
  const weaponRow = useCentredActive(`${query.weapon ?? ""}:${String(weapons.length)}`);

  return (
    <div className="space-y-2">
      <div ref={tileRow} className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
        {tiles.map((c) => {
          const active = c === "all" ? !query.category : query.category === c;
          return (
            <button
              key={c}
              type="button"
              aria-pressed={active}
              onClick={() => {
                haptic("select");
                onChange(
                  c === "all"
                    ? { category: undefined, weapon: undefined }
                    : { category: c, weapon: undefined },
                );
              }}
              className={`flex h-[60px] min-w-16 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border px-2 text-[11px] font-semibold ${
                active ? "border-primary text-primary" : "text-white/55"
              }`}
              style={active ? ACTIVE : SURFACE}
            >
              <SkinCategoryIcon category={c} />
              <span className="whitespace-nowrap">
                {c === "all" ? t("cs2.all") : t(`cs2.category.${c}`)}
              </span>
            </button>
          );
        })}
      </div>
      {(weapons.length > 1 || query.weapon !== undefined) && (
        <div ref={weaponRow} className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
          {weapons.map((w) => {
            const active = query.weapon === w;
            return (
              <button
                key={w}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  haptic("select");
                  onChange({ weapon: active ? undefined : w });
                }}
                className={`shrink-0 whitespace-nowrap rounded-xl border px-3 py-1.5 text-[12px] font-semibold ${
                  active ? "border-primary text-white" : "text-white/60"
                }`}
                style={active ? ACTIVE : SURFACE}
              >
                {w}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
