import { activeFilterCount, filterSections } from "@yupay/utils";
import { Check as CheckIcon, RotateCcw } from "lucide-react";
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
  const active = activeFilterCount(query);
  const href = (patch: SkinQueryPatch) => base + skinQueryString(query, patch);
  // Only the filters this category has: no wear on agents or cases, StatTrak only where
  // it exists, the category's own rarities (the weapon scale when none is picked).
  const show = filterSections(query.category, facets, query.rarity);

  return (
    <div>
      <SkinPriceFilter query={query} locale={locale} />

      {show.team && (
        <>
          <p className="text-tx-mute mb-1 mt-5 text-[12px] font-semibold uppercase">
            {t("team.title")}
          </p>
          <ul role="radiogroup" aria-label={t("team.title")}>
            {([undefined, "ct", "t"] as const).map((side) => {
              const on = query.team === side;
              return (
                <li key={side ?? "all"}>
                  <Link
                    href={href({ team: side })}
                    role="radio"
                    aria-checked={on}
                    className={option(on)}
                  >
                    <span
                      aria-hidden
                      className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${
                        on ? "border-primary" : "border-border-2"
                      }`}
                    >
                      {on && <span className="bg-primary size-2 rounded-full" />}
                    </span>
                    <span className="flex-1">{t(`team.${side ?? "all"}`)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}

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

      {active > 0 && (
        <Link
          href={href({
            exterior: undefined,
            rarity: undefined,
            team: undefined,
            stattrak: undefined,
            minUzs: undefined,
            maxUzs: undefined,
          })}
          className="border-border-2 text-tx-mute hover:border-primary hover:text-foreground mt-5 flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-[13px] font-semibold transition-colors"
        >
          <RotateCcw className="h-4 w-4" aria-hidden />
          {t("reset")}
          <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-[11px] font-bold leading-[18px]">
            {active}
          </span>
        </Link>
      )}
    </div>
  );
}
