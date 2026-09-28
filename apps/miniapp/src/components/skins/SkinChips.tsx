import { SKIN_CATEGORIES } from "@yupay/utils";

import type { SkinFacets, SkinItem, SkinQuery, SkinQueryPatch } from "@yupay/utils";

import { haptic } from "@/lib/telegram";
import { useT } from "@/lib/i18n";

function Chip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => {
        haptic("select");
        onClick();
      }}
      className={`shrink-0 whitespace-nowrap rounded-xl border px-3 py-1.5 text-[12px] font-semibold ${
        active ? "border-primary text-white" : "text-white/60"
      }`}
      style={{
        background: active ? "hsl(var(--primary) / 0.12)" : "hsl(var(--surface-2))",
        ...(active ? {} : { borderColor: "hsl(var(--border))" }),
      }}
    >
      {label}
    </button>
  );
}

/**
 * Category row, and — with a category chosen — its weapons. Weapons come from
 * the page on screen (the facets count the whole catalogue); the chosen weapon
 * always stays on the row, or a price filter that empties the page would leave
 * no way to unset it.
 */
export function SkinChips({
  query,
  facets,
  items,
  onChange,
}: {
  query: SkinQuery;
  facets: SkinFacets | undefined;
  items: SkinItem[];
  onChange: (patch: SkinQueryPatch) => void;
}) {
  const { t } = useT();
  const present = facets ? new Set(facets.categories.map((f) => f.value)) : null;
  const categories = SKIN_CATEGORIES.filter((c) => present === null || present.has(c));
  const onPage = items.map((i) => i.weapon).filter((w): w is string => w !== null);
  const weapons = query.category
    ? [...new Set(query.weapon ? [...onPage, query.weapon] : onPage)].sort()
    : [];

  return (
    <div className="space-y-2">
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
        <Chip
          active={!query.category}
          label={t("cs2.all")}
          onClick={() => onChange({ category: undefined, weapon: undefined })}
        />
        {categories.map((c) => (
          <Chip
            key={c}
            active={query.category === c}
            label={t(`cs2.category.${c}`)}
            onClick={() => onChange({ category: c, weapon: undefined })}
          />
        ))}
      </div>
      {(weapons.length > 1 || query.weapon !== undefined) && (
        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
          {weapons.map((w) => (
            <Chip
              key={w}
              active={query.weapon === w}
              label={w}
              onClick={() => onChange({ weapon: query.weapon === w ? undefined : w })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
