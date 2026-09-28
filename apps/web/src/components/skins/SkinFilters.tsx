import Link from "next/link";
import { useTranslations } from "next-intl";

import type { SkinQueryPatch, Exterior, SkinFacets, SkinQuery } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { DEFAULT_SORT, skinQueryString } from "@/lib/skins";

const PATH = "/skins";
const EXTERIORS: Exterior[] = ["FN", "MW", "FT", "WW", "BS"];

function option(active: boolean): string {
  return `flex items-center justify-between rounded-md px-2 py-1.5 text-[13px] transition ${
    active ? "bg-primary/10 text-foreground font-semibold" : "text-tx-mute hover:bg-muted"
  }`;
}

/**
 * The filter panel. Price is a GET form (works without JS, lands in the URL);
 * wear, rarity and StatTrak are links that toggle one value each. The page
 * places it twice: a sticky column on desktop, a bottom drawer on a phone.
 * Counts are scoped to the chosen category (the facets are).
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

  return (
    <div>
      <form method="get" action={base}>
        <p className="text-tx-mute mb-2 text-[12px] font-semibold uppercase">{t("price")}</p>
        {query.category && <input type="hidden" name="category" value={query.category} />}
        {query.weapon && <input type="hidden" name="weapon" value={query.weapon} />}
        {query.exterior && <input type="hidden" name="exterior" value={query.exterior} />}
        {query.rarity && <input type="hidden" name="rarity" value={query.rarity} />}
        {query.stattrak && <input type="hidden" name="stattrak" value="1" />}
        {query.q && <input type="hidden" name="q" value={query.q} />}
        {query.sort !== DEFAULT_SORT && <input type="hidden" name="sort" value={query.sort} />}
        <div className="flex items-center gap-2">
          <input
            type="number"
            name="min"
            min={0}
            inputMode="numeric"
            placeholder={t("from")}
            defaultValue={query.minUzs}
            className="border-border bg-background w-full rounded-lg border px-2 py-1.5 text-[13px]"
          />
          <span className="text-tx-dim">—</span>
          <input
            type="number"
            name="max"
            min={0}
            inputMode="numeric"
            placeholder={t("to")}
            defaultValue={query.maxUzs}
            className="border-border bg-background w-full rounded-lg border px-2 py-1.5 text-[13px]"
          />
        </div>
        <button
          type="submit"
          className="bg-primary text-primary-foreground mt-2 w-full rounded-lg py-1.5 text-[13px] font-semibold"
        >
          {t("apply")}
        </button>
      </form>

      <p className="text-tx-mute mb-1 mt-5 text-[12px] font-semibold uppercase">{t("wear")}</p>
      <ul>
        {EXTERIORS.map((e) => (
          <li key={e}>
            <Link
              href={href({ exterior: query.exterior === e ? undefined : e })}
              className={option(query.exterior === e)}
            >
              <span>{t(`exterior.${e}`)}</span>
              <span className="text-tx-dim font-mono text-[11px]">{wearCounts.get(e) ?? 0}</span>
            </Link>
          </li>
        ))}
      </ul>

      {facets.rarities.length > 0 && (
        <>
          <p className="text-tx-mute mb-1 mt-5 text-[12px] font-semibold uppercase">
            {t("rarity")}
          </p>
          <ul>
            {facets.rarities.map((r) => (
              <li key={r.value}>
                <Link
                  href={href({ rarity: query.rarity === r.value ? undefined : r.value })}
                  className={option(query.rarity === r.value)}
                >
                  <span className="flex items-center gap-2">
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

      <Link
        href={href({ stattrak: query.stattrak ? undefined : true })}
        className={`${option(query.stattrak === true)} mt-4`}
      >
        {t("stattrak")}
      </Link>

      <Link href={base} className="text-tx-dim mt-4 block text-center text-[13px] underline">
        {t("reset")}
      </Link>
    </div>
  );
}
