import { filterSections } from "@yupay/utils";
import { Check as CheckIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SkinPriceFilter } from "./SkinPriceFilter";

import type { SkinQueryPatch, Exterior, SkinFacets, SkinQuery } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { skinQueryString } from "@/lib/skins";

const PATH = "/skins";
const EXTERIORS: Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

function option(active: boolean): string {
  return `flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition ${
    active ? "text-foreground font-semibold" : "text-tx-mute hover:bg-muted hover:text-foreground"
  }`;
}

/** A ticked or empty box: which values are on reads at a glance (as on Waxpeer). */
function Check({ on }: { on: boolean }) {
  return (
    <span
      data-check={on ? "on" : "off"}
      aria-hidden
      className={`flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border-2 ${
        on ? "border-primary bg-primary text-primary-foreground" : "border-border-2"
      }`}
    >
      {on && <CheckIcon className="size-3" strokeWidth={3.5} />}
    </span>
  );
}

/**
 * The filter panel. Price applies itself as it is typed (`SkinPriceFilter`); wear,
 * rarity and StatTrak are links that toggle one value each, drawn as checkboxes. The page
 * places it twice: a sticky column on desktop, a bottom drawer on a phone.
 * Counts are scoped to the chosen category (the facets are), and so are the sections:
 * `filterSections` drops what the category does not have.
 */
export function SkinFilters({
  query,
  facets,
  locale,
}: {
  query: SkinQuery;
  facets: SkinFacets;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const base = pathFor(locale, PATH);
  const href = (patch: SkinQueryPatch) => base + skinQueryString(query, patch);
  const wearCounts = new Map(facets.exteriors.map((f) => [f.value, f.count]));
  // Only the filters this category has: no wear on agents or cases, StatTrak only where
  // it exists, the category's own rarities (the weapon scale when none is picked).
  const show = filterSections(query.category, facets, query.rarity);

  return (
    <div>
      <SkinPriceFilter query={query} locale={locale} />

      {show.wear && (
        <>
          <p className="text-tx-mute mb-1 mt-5 text-[12px] font-semibold uppercase">{t("wear")}</p>
          <ul>
            {EXTERIORS.map((e) => (
              <li key={e}>
                <Link
                  href={href({ exterior: query.exterior === e ? undefined : e })}
                  className={option(query.exterior === e)}
                  aria-current={query.exterior === e ? "true" : undefined}
                >
                  <Check on={query.exterior === e} />
                  <span className="flex-1">{t(`exterior.${e}`)}</span>
                  <span className="text-tx-dim font-mono text-[11px]">
                    {wearCounts.get(e) ?? 0}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {show.rarities.length > 0 && (
        <>
          <p className="text-tx-mute mb-1 mt-5 text-[12px] font-semibold uppercase">
            {t("rarity")}
          </p>
          <ul>
            {show.rarities.map((r) => (
              <li key={r.value}>
                <Link
                  href={href({ rarity: query.rarity === r.value ? undefined : r.value })}
                  className={option(query.rarity === r.value)}
                  aria-current={query.rarity === r.value ? "true" : undefined}
                >
                  <Check on={query.rarity === r.value} />
                  <span className="flex flex-1 items-center gap-2">
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: r.color ?? "currentColor" }}
                      aria-hidden
                    />
                    {r.value}
                  </span>
                  <span className="text-tx-dim font-mono text-[11px]">{r.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {(show.stattrak || query.stattrak === true) && (
        <Link
          href={href({ stattrak: query.stattrak ? undefined : true })}
          className={`${option(query.stattrak === true)} mt-4`}
          aria-current={query.stattrak ? "true" : undefined}
        >
          <Check on={query.stattrak === true} />
          {t("stattrak")}
        </Link>
      )}

      <Link href={base} className="text-tx-dim mt-4 block text-center text-[13px] underline">
        {t("reset")}
      </Link>
    </div>
  );
}
